"""端侧 TTS + 端侧 NLU 集成验收：跑真实 assistant.py（文字模式），验证两条链路。

模式 1（offline）：VOICE_OFFLINE=1，全离线——规则解析 + 端侧 NLU 兜底 + Piper 播报；
模式 2（degrade）：保留云端配置但把 XIAOMI_API_KEY 换成无效值，模拟云端不可用——
    云端 LLM/TTS 失败后自动降级到端侧 NLU + 端侧 TTS。

用法：
    C:\\va-venv\\Scripts\\python.exe tools\\test_assistant_integration.py offline
    C:\\va-venv\\Scripts\\python.exe tools\\test_assistant_integration.py degrade
输出：tools/test_assistant_integration_{mode}.out
"""
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

PY = sys.executable
MODES = {
    "offline": [
        "现在几点了",
        "现在这个点儿了",
        "把音量调到三十",
        "声音小一点",
        "把音量调到八十",
        "讲个笑话",
        "exit",
    ],
    "degrade": [
        "现在这个点儿了",
        "把音量调到八十",
        "讲个笑话",
        "exit",
    ],
}
EXPECT = {
    "offline": {
        "理解: '现在几点了' -> {'action': 'time'": "规则解析 time",
        "理解: '现在这个点儿了'": "端侧 NLU 兜底 time",
        "理解: '把音量调到三十' -> {'action': 'volume_set'": "规则解析 volume_set",
    },
    "degrade": {
        "[TTS] 云端合成失败": "云端 TTS 失败降级",
        "[NLU] 端侧": "云端 LLM 失败后走端侧 NLU",
    },
}


def log(lines, msg=""):
    print(msg, flush=True)
    lines.append(str(msg))


def current_volume():
    try:
        import actions

        return actions.get_volume()
    except Exception:
        return None


def restore_volume(pct):
    if pct is None:
        return
    try:
        import actions

        actions.set_volume(pct)
    except Exception:
        pass


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "offline").lower()
    if mode not in MODES:
        print(f"未知模式 {mode}，可选 {list(MODES)}")
        return 2
    out = BASE / "tools" / f"test_assistant_integration_{mode}.out"
    lines = []
    env = dict(os.environ)
    env.pop("VOICE_OFFLINE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    if mode == "offline":
        env["VOICE_OFFLINE"] = "1"
    else:
        env["XIAOMI_API_KEY"] = "sk-invalid-integration-test"
        env["MIMO_API_KEY"] = "sk-invalid-integration-test"

    vol_before = current_volume()
    log(lines, f"=== 集成测试 mode={mode} 当前音量={vol_before} ===")
    log(lines, f"命令: {MODES[mode]}")
    t0 = time.time()
    proc = subprocess.Popen(
        [PY, "assistant.py", "--text", "--no-hotkey"],
        cwd=str(BASE), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    peak_rss = [0]

    def sample():
        try:
            p = psutil.Process(proc.pid)
            while proc.poll() is None:
                try:
                    rss = p.memory_info().rss
                    for ch in p.children(recursive=True):
                        try:
                            rss += ch.memory_info().rss
                        except Exception:
                            pass
                    peak_rss[0] = max(peak_rss[0], rss)
                except Exception:
                    pass
                time.sleep(0.3)
        except Exception:
            pass

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    try:
        text = "\n".join(MODES[mode]) + "\n"
        output, _ = proc.communicate(text, timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
        log(lines, "!! 超时，已强制结束")
    finally:
        restore_volume(vol_before)
    elapsed = time.time() - t0
    log(lines, output or "(无输出)")
    log(lines, f"\n子进程退出码={proc.returncode} 总耗时={elapsed:.1f}s "
               f"峰值内存={peak_rss[0] / 1e6:.0f}MB（含 llama-server 子进程）")

    # ---- 校验 ----
    log(lines, "\n=== 校验 ===")
    ok_all = True
    if proc.returncode != 0:
        ok_all = False
        log(lines, f"FAIL 退出码 {proc.returncode}")
    for marker, desc in EXPECT[mode].items():
        hit = marker in (output or "")
        ok_all = ok_all and hit
        log(lines, f"{'PASS' if hit else 'FAIL'} {desc}: 期望出现 {marker!r}")
    n_nlu = len(re.findall(r"\[NLU\] 端侧", output or ""))
    n_tts = len(re.findall(r"\[TTS\] 端侧合成", output or ""))
    n_fail = len(re.findall(r"\[TTS\] 云端合成失败", output or ""))
    times = [float(m) for m in re.findall(r"\[TTS\] 端侧合成 (\d+) ms", output or "")]
    log(lines, f"端侧 NLU 解析次数={n_nlu}  端侧 TTS 播报次数={n_tts}  "
               f"云端 TTS 失败次数={n_fail}")
    if times:
        log(lines, f"端侧 TTS 合成耗时 P50={statistics.median(times):.0f}ms "
                   f"max={max(times):.0f}ms")
    min_tts = 3 if mode == "degrade" else 6
    if n_tts < min_tts:
        ok_all = False
        log(lines, f"FAIL 端侧播报次数 {n_tts} < {min_tts}")
    if mode == "offline" and n_nlu < 1:
        ok_all = False
        log(lines, "FAIL 端侧 NLU 未被调用")
    if mode == "degrade":
        if n_fail < 1:
            ok_all = False
            log(lines, "FAIL 没有观察到云端 TTS 失败降级")
        if n_nlu < 1:
            ok_all = False
            log(lines, "FAIL 没有观察到端侧 NLU 兜底")
    log(lines, f"\n结果: {'PASS' if ok_all else 'FAIL'}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"结果已写入 {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
