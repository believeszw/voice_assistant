"""端到端演示回放：把演示脚本的每一句真实说给助手听。

不是单测，也不是注入音频——用 SAPI 合成整句，从扬声器放出来，
麦克风收进 assistant 子进程，最后按 assistant 日志里的「动作」行判断过没过。

用法（必须用 C:\\va-venv 的 python，SAPI 在长路径解释器下会报错）：
  C:\\va-venv\\Scripts\\python.exe tools\\demo_e2e.py
"""
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sounddevice as sd  # noqa: E402

import actions  # noqa: E402

LOG = ROOT / "tools" / "demo_e2e_assistant.log"
REPORT = ROOT / "tools" / "demo_e2e_report.txt"
WAV_DIR = ROOT / "tools" / "demowav"
PY = os.environ.get("VA_PYTHON") or (
    r"C:\va-venv\Scripts\python.exe"
    if os.path.exists(r"C:\va-venv\Scripts\python.exe")
    else sys.executable
)


def render(text: str) -> Path:
    """SAPI 渲染成 wav（16k 单声道，方便扬声器播放）。"""
    import win32com.client
    WAV_DIR.mkdir(parents=True, exist_ok=True)
    path = WAV_DIR / (re.sub(r"[^\w]+", "_", text)[:24] + ".wav")
    if path.exists() and path.stat().st_size > 1000:
        return path
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 22  # SAFT16k16BitMono
    stream.Format = fmt
    stream.Open(str(path), 3, False)  # SSFMCreateForWrite
    old = voice.AudioOutputStream
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()
    voice.AudioOutputStream = old
    return path


def play(path: Path, gain: float = 3.0):
    with wave.open(str(path), "rb") as f:
        rate = f.getframerate()
        data = f.readframes(f.getnframes())
    import numpy as np
    arr = np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0
    # 本机扬声器→麦克风路径很弱（之前实测要用 6 倍增益唤醒才稳），默认给 4 倍并限幅
    sd.play(np.clip(arr * gain, -1.0, 1.0), rate)
    sd.wait()


_cursor = [0]  # 只在新日志里找，避免匹配到上一句留下的一模一样的行


def wait_log(pattern: str, timeout: float, what: str = "") -> bool:
    """轮询 assistant 日志的新增部分，等某一行出现。"""
    rx = re.compile(pattern)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if LOG.exists():
            text = LOG.read_text(encoding="utf-8", errors="replace")
            seg = text[_cursor[0]:]
            m = rx.search(seg)
            if m:
                _cursor[0] += m.end()
                print(f"  [命中] {m.group(0)[:120]}")
                return True
        time.sleep(0.25)
    print(f"  [超时] 等 {what or pattern} 没出现")
    try:
        tail = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-4:]
        for line in tail:
            print(f"    | {line}")
    except Exception:
        pass
    return False


def say_line(text: str, gain: float = 3.0):
    actions.set_volume(100)
    print(f"\n>> 我说：{text}")
    play(render(text), gain)


def wait_listening(timeout: float = 12) -> bool:
    """等助手真正进入「听」的状态再开口，否则会被它自己的播报盖住。"""
    got = wait_log(r"\[状态\] .*-> LISTENING", timeout, "进入 LISTENING")
    time.sleep(1.1)  # 等扬声器尾音散掉，避免把上一句回复录进去
    return got


def last_state() -> str:
    try:
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        m = re.search(r"\[状态\] \w+ -> (\w+)", line)
        if m:
            return m.group(1)
    return ""


def ensure_session() -> bool:
    """会话被静音超时结束后，自动再唤醒一次，别让后面的演示空喊。"""
    if last_state() == "IDLE":
        print("  [恢复] 会话已结束，重新唤醒")
        say_line("你好小助手")
        return wait_listening(12)
    return True


def after_reply(timeout: float = 20) -> bool:
    """等助手把当前回复播完、回到 LISTENING，再说下一句，避免自己插自己的话。"""
    got = wait_log(r"\[状态\] (?:SPEAKING|INTERRUPTED) -> LISTENING", timeout, "回复播完")
    time.sleep(0.5)
    return got


def sync_before_speak(timeout: float = 15) -> bool:
    """确认助手此刻真的在听；若会话已结束先重新唤醒。"""
    st = last_state()
    if st == "LISTENING":
        time.sleep(0.3)
        return True
    if st == "IDLE":
        return ensure_session()
    if wait_listening(timeout):
        return True
    return ensure_session()


def _kill_stale_assistant():
    """杀掉上次跑残留下来的 assistant.py（它会占着麦克风和日志文件）。"""
    try:
        import psutil
    except Exception:
        return
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info["pid"] == me or p.info["name"] != "python.exe":
                continue
            cmd = " ".join(p.info["cmdline"] or [])
            if "assistant.py" in cmd and "--no-hotkey" in cmd:
                p.kill()
        except Exception:
            continue
    time.sleep(0.8)


def main():
    _kill_stale_assistant()
    global LOG
    try:
        if LOG.exists():
            LOG.unlink()
    except PermissionError:
        LOG = ROOT / "tools" / f"demo_e2e_assistant_{int(time.time())}.log"
        print(f"[warn] 旧日志被占用，改用 {LOG.name}")
    if REPORT.exists():
        try:
            REPORT.unlink()
        except PermissionError:
            pass
    # 先把输出设备弄响：有人可能被之前的「静音」测试留在 mute 状态
    try:
        import actions
        actions.mute(False)
        actions.set_volume(100)
    except Exception as exc:
        print("音量预置失败（继续）:", exc)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # 真实模式：会真的开记事本、调音量；不测「关机」（避免真关机）
    log_f = open(LOG, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [PY, "-u", "assistant.py", "--no-hotkey"],
        cwd=str(ROOT), env=env, stdout=log_f, stderr=subprocess.STDOUT,
    )
    ok = {}
    _cursor[0] = 0
    try:
        print("等待助手启动（加载 KWS / sherpa 模型）...")
        if not wait_log(r"\[唤醒词\]", 120, "启动完成"):
            ok["启动"] = False
            return
        ok["启动"] = True
        # 启动问候语不打印「SPEAKING -> IDLE」，且云端 TTS 可能要好几秒才播完；
        # 等 12s 再开口，否则会被礼貌地「打断」掉，助手又回去等唤醒词。
        time.sleep(14.0)

        # 演示 1：唤醒 + 时间（最多喊 3 次；第一次可能撞上开机问候尾巴）
        woke = False
        for attempt in range(4):
            say_line("你好小助手")
            if wait_log(r"\[助手\] 我在|\[状态\] .*WAKING", 8, "唤醒回应"):
                woke = True
                break
            time.sleep(2.0)
        ok["0_唤醒"] = woke
        # 等「我在」播完、真正进入 LISTENING 再说话，否则会被自己的回复盖住
        wait_listening(12)
        say_line("现在几点了")
        ok["1_唤醒+时间"] = wait_log(r"\[动作\] time", 12, "time 动作")
        after_reply()

        # 演示 2：多轮 + 音量（演示脚本原本说「静音」，但那会把整机静音、后面几步都听不见，
        # 这里改成 调到三十 → 调回八十，既展示音量控制又不把链路弄哑）
        say_line("把音量调到三十")
        ok["2a_音量30"] = wait_log(r"\[动作\] volume_set", 10, "volume_set 30")
        after_reply()
        # 先把音量恢复，否则后面命令外放声音太小、麦克风收不到
        try:
            import actions
            actions.set_volume(80)
        except Exception:
            pass
        time.sleep(0.4)
        sync_before_speak()
        say_line("把音量调到八十")
        ok["2b_音量80"] = wait_log(r"\[动作\] volume_set", 10, "volume_set 80")
        after_reply()

        # 演示 3：一句话多指令
        sync_before_speak()
        say_line("打开记事本，然后调大音量到六十")
        ok["3_复合指令"] = wait_log(r"\[动作\] open_app", 12, "open_app")
        ok["3b_复合音量"] = wait_log(r"\[动作\] volume_set", 8, "volume_set 60")
        # 留一张屏幕证据，便于确认窗口是真的打开了还是被别的全屏窗口挡住
        try:
            import actions as _act
            _ok, _msg = _act.screenshot()
            print(f"  [证据] 截图 {_msg}")
        except Exception as exc:
            print("  [证据] 截图失败:", exc)
        after_reply()

        # 演示 4：播报中插话，接住下一句
        sync_before_speak()
        say_line("讲个笑话")
        wait_log(r"\[状态\] SPEAKING", 12, "开始播报笑话")
        # 云端 TTS 合成要 1-2 秒，等 4 秒确保笑话真的开始放了再插话，否则会「没讲就打断」
        time.sleep(4.0)
        say_line("停一下，现在几点了")
        interrupted = wait_log(r"\[打断\].*停止播报", 8, "打断确认")
        ok["4_打断"] = interrupted
        ok["4b_接住下一句"] = wait_log(r"\[动作\] time", 12, "打断后的 time")
        after_reply()

        # 演示 7：云端闲聊
        sync_before_speak()
        say_line("今天天气怎么样")
        ok["7_闲聊"] = wait_log(r"\[状态\] THINKING -> SPEAKING|\[动作\] chat|\[LLM\]", 25, "闲聊回复")
        after_reply(25)

        # 收尾
        for attempt in range(3):
            time.sleep(0.5)
            word = "退出" if attempt < 2 else "结束"
            sync_before_speak()
            say_line(word)
            if wait_log(r"好的，再见", 8, "退出"):
                ok["退出"] = True
                break
        if "退出" not in ok:
            ok["退出"] = False
    finally:
        # 让助手自己退出；超时强杀
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        log_f.close()
        _kill_stale_assistant()

    print("\n==== 演示回放结果 ====")
    passed = 0
    lines = ["演示回放结果（真实扬声器 → 麦克风 → assistant 子进程）", ""]
    for k, v in ok.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
        lines.append(f"{'PASS' if v else 'FAIL'}  {k}")
        passed += bool(v)
    lines.append("")
    lines.append(f"{passed}/{len(ok)} 项通过")
    lines.append(f"助手日志：{LOG}")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"  {passed}/{len(ok)} 项通过")
    print(f"  助手日志：{LOG}")
    return 0 if passed == len(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
