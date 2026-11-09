"""语音助手主程序。

用法：
  python assistant.py            # 语音模式：唤醒词唤醒，唤醒后可以连续对话
  python assistant.py --text     # 文字模式，键盘输入指令（测试用）
  python assistant.py --dry-run  # 演练模式：危险操作只提示不执行

能力：
- 端侧优先：唤醒、VAD、AEC、识别（sherpa-onnx 双遍）、规则意图都在本地；云端只在
  本地没听清或解析不出意图时兜底，以及闲聊/知识问答（参照小米车机助手的做法）
- 说完一句后可以在 6 秒内接着说，不用重新唤醒；说“退出/结束/再见”结束
- 播报双路：优先云端 TTS（音色自然，并给 AEC 提供参考信号），失败/超时/断网退端侧
  sherpa-onnx VITS（离线、可暂停），最后才退 SAPI
"""

import argparse
import datetime
import re
import time
import traceback

import actions
import asr
import asr_local
import audio
import config
import kws as kws_mod
import llm
import nlu_local
from config import (CLOUD_ASR, CLOUD_ENABLED, CLOUD_LLM, CLOUD_TTS,
                    COMMAND_MAX_SECONDS, COMMAND_SILENCE_SECONDS, DANGEROUS,
                    FOLLOWUP_START_TIMEOUT, SAMPLE_RATE, SESSION_MAX_TURNS,
                    TTS_VOICE, WAKE_ACK, WAKE_WORDS, WAKE_WORDS_FUZZY)
from frontend import AudioFrontend, enhance_pcm
from hotkey import Hotkeys
from intents import cn2int, parse
from tts import Speaker

WAKE_ALL = tuple(dict.fromkeys(WAKE_WORDS + WAKE_WORDS_FUZZY))

# 一句话里的多个指令：「打开记事本，然后调大音量」「静音，再截个屏」
_COMPOUND_SPLIT = re.compile(r"[，,；;]\s*(?:然后|接着|再|并且|并)?|然后|接着|并且")


_CLAUSE_PREFIX = re.compile(r"^(?:再|然后|接着|并且|并|之后)\s*")

# 识别器偶尔会把环境音/口头词吐成「Yeah。」「嗯。」这类东西。它们既不是指令，
# 也不该触发闲聊——否则一次演示会被这种噪声吃掉一轮对话额度。
_NOISE_STRIP = re.compile(r"[\s，。,.!?！？、；;：:…~～\"'“”‘’()（）\[\]【】]+")
_NOISE_WORDS = {
    "yeah", "yes", "yep", "ok", "okay", "hi", "hello", "hey", "fine",
    "thanks", "thank", "thankyou", "you", "i",
    "嗯", "啊", "哦", "呃", "唔", "诶", "哎", "唉", "呀", "哈", "呵", "嘿",
    "那个", "这个", "好的",
}


def _is_noise(text: str) -> bool:
    """判断识别结果是不是「非指令的噪声」：纯标点、单字、口头词。"""
    t = _NOISE_STRIP.sub("", text or "").strip().lower()
    if len(t) <= 1:
        return True
    return t in _NOISE_WORDS


# 口语句首的填充词：「嗯，帮我打开记事本」「那个，现在几点了」
_FILLER_PREFIX = re.compile(
    r"^(?:(?:嗯|呃|啊|哦|诶|哎|唉|唔|那个|这个|就是|然后|喂|你好|您好|"
    r"小朋友|小助手|在吗|请|麻烦|帮我)\s*[，,。.！!？?、]?\s*)+"
)


def _strip_fillers(text: str) -> str:
    """去掉句首口头词/连接词，返回真正像指令的部分。"""
    prev = None
    t = (text or "").strip()
    while prev != t:
        prev = t
        t = _FILLER_PREFIX.sub("", t).strip("，,。.！!？?、 ")
    return t


# 子句开头常被 ASR 带上来的口水话/代词：「的话，你打开记事本」「你帮我…」
_LEAD_NOISE = re.compile(
    r"^(?:(?:的话|那么|那个|这个|就是|然后|所以|但是|不过|你|您|我|我们|咱们|"
    r"帮我|请|麻烦|先|就)\s*[，,。.！!？?、]?\s*)+"
)


def _strip_lead(text: str) -> str:
    """去掉子句开头的「的话，你」这类残留，便于规则解析。"""
    t = (text or "").strip()
    prev = None
    while prev != t:
        prev = t
        t = _LEAD_NOISE.sub("", t).strip("，,。.！!？?、 ")
    return t


# 复合指令里的「等2秒钟之后」——演示里会拿它验证按序执行
_DELAY_RE = re.compile(
    r"^(?:等|等待|过|停)\s*([0-9零一二两三四五六七八九十百]+)\s*"
    r"(秒钟|秒|分钟|分)\s*(?:之后|以后|后)?\s*[，,。.]?\s*"
)


def _take_delay(text: str):
    """取出开头的等待时间，返回 (秒数或 0, 剩余文本)。"""
    m = _DELAY_RE.match(text or "")
    if not m:
        return 0.0, text
    value = cn2int(m.group(1))
    if value is None:
        return 0.0, text
    unit = 60 if "分" in m.group(2) else 1
    return float(value * unit), text[m.end():].strip()


def split_compound(text: str):
    """把复合指令拆成子句；不足两句返回空列表（走单指令逻辑）。

    拆分后剥掉开头连接词（「再/然后/接着/并且」），这样第二句可以是
    「再调到百分之五十」这种省略主语的补充指令。
    """
    raw = [p.strip("，,；; 。.!！?？、") for p in _COMPOUND_SPLIT.split(text or "")]
    parts = []
    for p in raw:
        p = _CLAUSE_PREFIX.sub("", p).strip()
        if p:
            parts.append(p)
    return parts if len(parts) > 1 else []

HELP = (
    "我能做这些事：打开或关闭应用，比如打开记事本、关闭计算器；"
    "控制音量，比如音量调大、静音、音量调到五十；"
    "播放控制，下一首、暂停；截屏、锁屏、显示桌面；"
    "搜索、查时间日期、看内存电量；复制、读剪贴板、输入文字；"
    "打开下载或文档文件夹；关机、重启、睡眠。"
    "一句话可以说多个指令，比如「打开记事本，然后调大音量」；"
    "说完一句 6 秒内可以直接接着说，不用再唤醒。"
)


class Assistant:
    def __init__(self, text_mode=False, dry_run=False, use_hotkey=True, use_wake=True):
        self.text_mode = text_mode
        self.dry_run = dry_run
        self.use_wake = use_wake
        self.speaker = Speaker()
        self.cloud_asr = CLOUD_ENABLED and CLOUD_ASR and llm.available()
        self.cloud_llm = CLOUD_ENABLED and CLOUD_LLM and llm.available()
        self.cloud_tts = CLOUD_ENABLED and CLOUD_TTS and llm.available()
        self.fe = AudioFrontend()
        self.speaker.far_sink = self.fe.push_far
        self.state = "IDLE"
        self._mic = None
        self._interrupted = False
        self._pre_pcm = b""
        self.hotkeys = None
        if use_hotkey and not text_mode:
            self.hotkeys = Hotkeys()
            self.hotkeys.start()

    def _set_state(self, state: str):
        if state != self.state:
            self.log(f"[状态] {self.state} -> {state}")
            self.state = state

    # ---------------- 输出 ----------------
    def say(self, text: str):
        """朗读一段话；语音模式下播放期间监听打断（barge-in）。

        打断做成两步，避免「咳嗽一声就把整句砍掉」：
        1) 检测到插话先暂停播报（可恢复）；
        2) 快速确认是不是真人在说话——真打断就丢掉剩余播报，并把预录的
           开头接到下一轮识别；假打断就继续播。
        """
        if not text:
            return
        if self.text_mode or self._mic is None or not self.cloud_tts:
            self.speaker.say(text)
            return
        if text == WAKE_ACK and hasattr(self.speaker, "say_quick"):
            # 唤醒回应走本地短句，省掉云端合成的约 1 秒延迟
            self.speaker.say_quick(text)
            return
        self._set_state("SPEAKING")
        self._interrupted = False
        self._pre_pcm = b""
        self.fe.reset()
        done = self.speaker.say_async(text)
        started = time.time()
        try:
            while not done.is_set():
                block = self._mic.read(0.05)
                if not block:
                    continue
                self.fe.process(block)
                if not self.fe.barge_in or time.time() - started <= 0.30:
                    continue
                if not self.speaker.pause():
                    # 后端不支持暂停（如 SAPI）：直接按真打断处理
                    self.log(f"[打断] 用户插话，停止播报（{self.fe.barge_evidence}）")
                    self.speaker.discard()
                    self._pre_pcm = self._capture_after_barge(0.55)
                    self._interrupted = True
                    self._set_state("INTERRUPTED")
                    break
                confirmed, confirm_pcm = self._confirm_barge(0.55)
                if confirmed:
                    self.log(f"[打断] 确认在说话，停止播报（{self.fe.barge_evidence}）")
                    self.speaker.discard()
                    self._pre_pcm = self._capture_after_barge(0.55, confirm_pcm)
                    self._interrupted = True
                    self._set_state("INTERRUPTED")
                    break
                self.log("[打断] 只是噪声/漏音，继续播报")
                self.speaker.resume()
                self.fe.reset()
        finally:
            self.fe.reset()

    def _confirm_barge(self, seconds: float):
        """暂停后听一小段，确认刚才是不是真有人说话。

        播报已经暂停，此时麦克风里基本只剩环境噪声，所以用绝对能量就够；
        要求至少 3 个 50ms 块超过阈值，避免咳嗽/键盘声这种单帧噪声。
        返回 (是否真打断, 这一小段录到的 PCM)——这段音频不能丢，否则用户
        在「暂停→确认」窗口里说的话会被吞掉。
        """
        if self._mic is None:
            return False, b""
        chunks = []
        loud = 0
        very_loud = 0
        self._mic.flush()
        deadline = time.time() + seconds
        settle_until = time.time() + min(0.30, max(0.20, seconds * 0.5))
        while time.time() < deadline:
            block = self._mic.read(0.05)
            if not block:
                continue
            if time.time() < settle_until:
                # 暂停后 OutputStream 里还有约 100~300ms 的播放尾巴；
                # 这段必须丢掉，否则「自己的尾音」会被当成用户在确认说话。
                continue
            chunks.append(block)
            rms = audio.rms_of(block)
            if rms > 0.035:
                loud += 1
            if rms > 0.08:
                very_loud += 1
        # 单块响不排除是关节声/尾音；要求持续 4 块，或至少 2 块明显高于说话音量
        return (loud >= 4 or very_loud >= 2), b"".join(chunks)

    @staticmethod
    def _trim_pre_roll(pcm: bytes, frame: int = 1600) -> bytes:
        """裁掉预录里开口前的低能量段（回声尾巴/静音），从用户真正开口处开始。"""
        if not pcm:
            return pcm
        import numpy as np

        x = np.frombuffer(pcm, dtype=np.int16)
        n = x.size // frame
        if n < 2:
            return pcm
        blocks = x[: n * frame].astype(np.float32) / 32768.0
        rms = np.sqrt((blocks.reshape(n, frame) ** 2).mean(axis=1))
        thr = max(0.012, float(rms.max()) * 0.25)
        idx = np.where(rms > thr)[0]
        start = int(idx[0]) if idx.size else n - 1
        start = max(0, start - 1)  # 多留一帧，避免切掉起音
        return x[start * frame:].tobytes()

    def _capture_after_barge(self, seconds: float, confirm_pcm: bytes = b"") -> bytes:
        """打断后继续收一小段，与预录拼成下一句的开头（补回被切掉的字）。

        用「原始麦克风」预录：AEC 的残余回声抑制在双讲时会压低人声，
        用 clean 信号做预录会把「停一下」这类开头削掉。
        顺序：原始预录（自动裁到开口处）→ 确认窗口录音 → 打断后补录。
        """
        chunks = [self._trim_pre_roll(self.fe.recent_near(0.9)), confirm_pcm]
        deadline = time.time() + seconds
        while time.time() < deadline and self._mic is not None:
            block = self._mic.read(0.05)
            if not block:
                continue
            chunks.append(block)
            self.fe.process(block)
        return b"".join(chunks)

    def log(self, text: str):
        line = f"{datetime.datetime.now():%H:%M:%S} {text}"
        print(line)

    # ---------------- 识别 ----------------
    def _asr(self, pcm: bytes, local_result=None):
        """返回 (文本, 引擎)。

        端侧优先（参照小米车机助手）：
          1) 本地双遍（流式 Paraformer + SenseVoice 校正）先出结果；
          2) 结果为空/太短，且云端可用 → 云端 MiMo 兜底；
          3) 云端也不可用 → Vosk 最后兜底。
        ASR_LOCAL_FIRST=False 时退回旧的「云端优先」行为。
        """
        text, engine = local_result if local_result else ("", "none")
        text = (text or "").strip()
        min_chars = getattr(config, "ASR_LOCAL_MIN_CHARS", 2)
        confident = bool(text) and len(text) >= min_chars

        if getattr(config, "ASR_LOCAL_FIRST", True):
            if confident:
                return text, f"local:{engine}"
            if self.cloud_asr and getattr(config, "ASR_CLOUD_FALLBACK", True):
                try:
                    cloud = llm.asr_pcm(pcm, SAMPLE_RATE)
                    if cloud:
                        if text:
                            self.log(f"[ASR] 本地结果过短({text!r})，改用云端: {cloud!r}")
                        return cloud, "cloud"
                except Exception as exc:
                    self.log(f"[ASR] 云端兜底失败，继续用本地: {str(exc)[:120]}")
            if text:
                return text, f"local:{engine}"
            return asr.transcribe_pcm(pcm), "vosk"

        # 旧策略：云端优先
        if self.cloud_asr:
            try:
                cloud = llm.asr_pcm(pcm, SAMPLE_RATE)
                if cloud:
                    return cloud, "cloud"
            except Exception as exc:
                self.log(f"[ASR] 云端识别失败，退回本地: {str(exc)[:120]}")
        if text:
            return text, f"local:{engine}"
        return asr.transcribe_pcm(pcm), "vosk"

    # ---------------- 理解与执行 ----------------
    def handle(self, text: str, history=None):
        """返回 (回复文本, 是否退出)。支持一句话多个指令。"""
        history = history or []
        text = _strip_fillers(text or "")
        if not text:
            return "嗯，我在。", False
        # 只有唤醒词/问候（「你好，小助手」）当作打招呼，不要报「没听懂」
        if not self._strip_wake(text):
            return "你好，我在。", False
        parts = split_compound(text)
        cleaned = []
        for p in parts:
            p = _strip_fillers(self._strip_wake(p))
            lead = _strip_lead(p)
            p = lead or p
            if p and not _is_noise(p):
                cleaned.append(p)
        if len(cleaned) >= 2:
            parts = cleaned
        else:
            parts = []
        if len(parts) >= 2:
            intents = []
            fixed = []
            for p in parts:
                cand = _strip_lead(p)
                it = parse(cand)
                if it.get("action") in (None, "unknown") and cand != p:
                    it = parse(p)
                    cand = p
                intents.append(it)
                fixed.append(cand)
            parts = fixed
            known = [i.get("action") not in (None, "unknown") for i in intents]
            if any(known):
                replies = []
                should_exit = False
                for part, intent, ok in zip(parts, intents, known):
                    delay, part = _take_delay(part)
                    if delay:
                        self.log(f"[等待] {delay:g} 秒")
                        time.sleep(min(delay, 5.0))
                        part = _strip_fillers(part)
                        if not part:
                            continue
                        intent = parse(part)
                        ok = intent.get("action") not in (None, "unknown")
                    if not ok:
                        # 不能静默丢掉：明确告诉用户哪句没听懂
                        replies.append(f"「{part}」这句没听懂")
                        continue
                    self.log(f"理解(复合): {part!r} -> {intent}")
                    reply, exit_now = self.execute(intent, text=part, history=history)
                    replies.append(reply)
                    should_exit = should_exit or exit_now
                    if exit_now:
                        break
                return "；".join(replies), should_exit
        intent = parse(text)
        if intent.get("action") == "unknown":
            lead = _strip_lead(text)
            if lead != text:
                alt = parse(lead)
                if alt.get("action") not in (None, "unknown"):
                    text = lead
                    intent = alt
        if intent.get("action") == "unknown":
            llm_intent = self._llm_understand(text, history)
            if llm_intent and llm_intent.get("action") not in (None, "unknown"):
                intent = llm_intent
        self.log(f"理解: {text!r} -> {intent}")
        return self.execute(intent, text=text, history=history)

    def _llm_understand(self, text: str, history):
        """规则没命中时的语义兜底：云端 LLM 优先，端侧小模型离线兜底。"""
        if self.cloud_llm:
            try:
                intent = llm.understand(text, history)
            except Exception as exc:
                intent = None
                self.log(f"[LLM] 意图解析失败: {str(exc)[:120]}")
            if intent and intent.get("action") not in (None, "unknown"):
                return intent
        if config.NLU_LOCAL_ENABLED and nlu_local.available():
            try:
                intent = nlu_local.parse(text, history)
            except Exception as exc:
                self.log(f"[NLU] 端侧解析失败: {str(exc)[:120]}")
                return None
            if intent:
                stats = nlu_local.last_stats()
                self.log(f"[NLU] 端侧 {stats.get('mode', '')} {stats.get('ms', 0):.0f} ms "
                         f"prompt={stats.get('prompt_tokens')} gen={stats.get('completion_tokens')}")
                return intent
        return None

    def execute(self, intent: dict, text: str = "", history=None):
        action = intent.get("action")
        name = intent.get("name", "")
        history = history or []

        if action == "exit":
            return "好的，再见。", True
        if action == "stop_speaking":
            self.speaker.stop()
            return "好。", False
        if action == "greet":
            return "你好，我在。", False
        if action == "help":
            return HELP, False
        if action == "chat":
            reply = self._chat_reply(text, history)
            return reply or "这个我还答不上来。", False
        if action == "unknown":
            reply = self._chat_reply(text, history)
            if reply:
                return reply, False
            return "没听懂。可以说“打开记事本”“现在几点”“音量调大”。", False

        if action in DANGEROUS:
            question = {
                "shutdown": "确定要关机吗",
                "restart": "确定要重启吗",
                "sleep": "确定要睡眠吗",
                "lock": "确定要锁屏吗",
                "close_app": f"确定要关闭{name}吗",
            }.get(action, "确定要执行吗")
            if self.dry_run:
                return f"（演练模式）跳过：{action} {name}".strip(), False
            if not self._confirm(question):
                return "已取消。", False

        try:
            reply, should_exit = self._dispatch(intent)
            self.log(f"[动作] {action} -> {reply}")
            return reply, should_exit
        except Exception as exc:  # pragma: no cover
            self.log(traceback.format_exc())
            return f"执行出错：{exc}", False

    def _chat_reply(self, text: str, history) -> str:
        if not self.cloud_llm or not text:
            return ""
        try:
            return llm.chat_reply(text, history)
        except Exception as exc:
            self.log(f"[LLM] 闲聊失败: {str(exc)[:120]}")
            return ""

    def _dispatch(self, intent: dict):
        action = intent.get("action")
        name = intent.get("name", "")

        if action == "open_app":
            ok, msg = actions.open_app(name)
        elif action == "close_app":
            ok, msg = actions.close_app(name)
        elif action == "volume_up":
            ok, msg = actions.volume_step(+5)
        elif action == "volume_down":
            ok, msg = actions.volume_step(-5)
        elif action == "volume_set":
            ok, msg = actions.set_volume(intent["value"])
        elif action == "volume_max":
            ok, msg = actions.volume_max()
        elif action == "volume_get":
            cur = actions.get_volume()
            ok, msg = True, (f"当前音量 {cur}%" if cur is not None else "音量未知")
        elif action == "mute":
            ok, msg = actions.mute(True)
        elif action == "unmute":
            ok, msg = actions.mute(False)
        elif action == "media_play_pause":
            ok, msg = actions.media_play_pause()
        elif action == "media_next":
            ok, msg = actions.media_next()
        elif action == "media_prev":
            ok, msg = actions.media_prev()
        elif action == "screenshot":
            ok, msg = actions.screenshot()
        elif action == "lock":
            ok, msg = actions.lock_screen()
        elif action == "sleep":
            ok, msg = actions.sleep_pc()
        elif action == "shutdown":
            ok, msg = actions.shutdown_pc(20)
        elif action == "restart":
            ok, msg = actions.restart_pc(20)
        elif action == "cancel_shutdown":
            ok, msg = actions.cancel_shutdown()
        elif action == "search":
            ok, msg = actions.search_web(intent["term"])
        elif action == "open_url":
            ok, msg = actions.open_url(intent["url"])
        elif action == "time":
            ok, msg = actions.tell_time()
        elif action == "date":
            ok, msg = actions.tell_date()
        elif action == "system_info":
            ok, msg = actions.system_info()
        elif action == "copy_text":
            ok, msg = actions.copy_text(intent["text"])
        elif action == "read_clipboard":
            ok, msg = actions.read_clipboard()
        elif action == "type_text":
            ok, msg = actions.type_text(intent["text"])
        elif action == "show_desktop":
            ok, msg = actions.show_desktop()
        elif action == "open_folder":
            ok, msg = actions.open_folder(intent["name"])
        elif action == "brightness":
            ok, msg = actions.brightness(intent["delta"])
        else:
            ok, msg = False, f"暂不支持：{action}"
        return msg, False

    def _confirm(self, question: str) -> bool:
        if self.text_mode:
            try:
                ans = input(f"{question}（输入 确认/取消）> ").strip()
            except EOFError:
                return False
            return ans in ("确认", "确定", "是", "好", "可以", "y", "yes")
        self.say(question + "，说“确认”或者“取消”。")
        with audio.Mic() as mic:
            pcm, _, ok = audio.record_utterance(
                mic, max_seconds=4, silence_seconds=0.7, start_timeout=4)
        if not ok:
            return False
        text, _ = self._asr(pcm)
        self.log(f"确认回答: {text!r}")
        return any(w in text for w in ("确认", "确定", "是", "好", "可以"))

    # ---------------- 文字模式 ----------------
    def run_text(self):
        mode = "云端增强" if (self.cloud_asr or self.cloud_llm) else "纯本地"
        print(f"文字模式（{mode}）。输入指令，输入 exit 退出。")
        self.say("文字模式已启动。")
        history = []
        while True:
            try:
                line = input("你说> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.lower() in ("exit", "quit", "q"):
                break
            reply, should_exit = self.handle(line, history)
            self.say(reply)
            history.append({"role": "user", "content": line})
            history.append({"role": "assistant", "content": reply})
            if should_exit:
                break

    # ---------------- 语音模式 ----------------
    def run_voice(self):
        mic = audio.Mic()
        mic.start()
        self._mic = mic
        self._set_state("IDLE")
        try:
            self.local_asr = asr_local.TwoPassASR(log=self.log)
        except Exception as exc:
            self.local_asr = None
            self.log(f"[ASR] 本地双遍不可用: {str(exc)[:120]}")
        local_ok = bool(self.local_asr and self.local_asr.available())
        print(f"[麦克风] {mic.name}")
        engine = "云端 MiMo 主力" if self.cloud_asr else "本地识别"
        print(f"[识别] {engine}；本地双遍(sherpa-onnx): {'可用' if local_ok else '不可用'}")
        try:
            self.kws = kws_mod.WakeWord(log=self.log)
        except Exception as exc:  # noqa: BLE001
            self.kws = None
            self.log(f"[KWS] 加载失败: {str(exc)[:120]}")
        wake_ok = bool(self.kws and self.kws.available())
        print(f"[唤醒] KWS 本地模型: {'可用' if wake_ok else '不可用（退回文本匹配）'}"
              f"；热键 Ctrl+Alt+Space")
        print(f"[唤醒词] {' / '.join(WAKE_WORDS)}")
        # 提示语里不要念出唤醒词本身，否则会被自己的扬声器触发
        self.say("语音助手已启动。说唤醒词，或者按 Ctrl Alt 空格 叫我。")
        mic.flush()

        stream = asr.StreamASR()
        last_wake = 0.0
        try:
            while True:
                if self.hotkeys and self.hotkeys.stop.is_set():
                    self.hotkeys.stop.clear()
                    self.speaker.stop()
                    continue
                if self.hotkeys and self.hotkeys.wake.is_set():
                    self.hotkeys.wake.clear()
                    self.log("热键唤醒")
                    self._enter_session(mic, stream)
                    continue

                block = mic.read(0.2)
                if block is None:
                    continue

                # 音频前端：去回声 → 降噪 → 自动增益；唤醒和兜底识别都吃增强后的信号
                enh, _prob, _active = self.fe.process(block, enhanced=True)
                if not enh:
                    enh = block

                # 1) 专用 KWS 模型（主路径）：只认注册的关键词，几 MB、1% CPU
                kw = self.kws.feed(enh) if wake_ok else None
                if kw:
                    now = time.time()
                    if now - last_wake >= 1.0:
                        last_wake = now
                        self.log(f"KWS 唤醒: {kw!r}")
                        self._enter_session(mic, stream)
                    continue

                # 2) 文本匹配（兜底）：KWS 不可用，或一句话里带指令（“小助手，现在几点了”）
                final = stream.accept(enh)
                text = final if final else stream.partial()
                if not text or not self.use_wake:
                    continue
                if any(w in text for w in WAKE_ALL):
                    now = time.time()
                    if now - last_wake < 2.0:
                        continue
                    last_wake = now
                    self.log(f"唤醒词命中: {text!r}")
                    rest = self._strip_wake(text)
                    if _is_noise(rest):
                        # 模糊唤醒词带出的单个字（「你好小姐」→「姐」）不是指令
                        rest = ""
                    self._enter_session(mic, stream, rest)
        finally:
            mic.stop()
            if self.hotkeys:
                self.hotkeys.stop_listening()
            self.speaker.shutdown()

    def _enter_session(self, mic, stream, initial_text=""):
        stream.reset()
        mic.flush()
        if getattr(self, "kws", None):
            self.kws.reset()
        try:
            self.fe.reset()
        except Exception:
            pass
        self._session(mic, initial_text)
        stream.reset()
        mic.flush()
        if getattr(self, "kws", None):
            self.kws.reset()

    def _strip_wake(self, text: str) -> str:
        """把「小助手，现在几点了」里的唤醒词去掉，返回后半句指令。

        模糊唤醒会匹配到近音字（「你好小姐」→「你好小」），剩下的单个字
        （「姐」）或者「你要」这种两字残渣都不是指令，必须丢掉，否则会被
        当成一句话执行。
        """
        rest = text or ""
        for w in sorted(WAKE_ALL, key=len, reverse=True):
            rest = rest.replace(w, "")
        rest = _strip_fillers(rest).strip("，。,.!?！？、 　")
        if not rest or len(rest) <= 1:
            return ""
        # 两三个字的残渣，如果规则也解析不出动作，就按残留噪声处理
        if len(rest) <= 3 and parse(rest).get("action") == "unknown":
            return ""
        return rest

    def _session(self, mic, initial_text=""):
        """一次唤醒后的连续对话。"""
        self._set_state("WAKING")
        self.say(WAKE_ACK)
        mic.flush()
        history = []
        pcm = None
        turn = 0
        rounds = 0
        while turn < SESSION_MAX_TURNS:
            rounds += 1
            if rounds > SESSION_MAX_TURNS * 2:  # 防止被连续打断时无限循环
                break
            # 上一轮被打断：把打断瞬间录到的开头接回来，避免第一句话被切头
            pre = b""
            if turn > 0 and self._interrupted:
                pre = self._pre_pcm or b""
                self._pre_pcm = b""
                self._interrupted = False
            if turn == 0 and initial_text and not _is_noise(initial_text):
                text, engine, secs = initial_text, "wake", 0.0
            else:
                self._set_state("LISTENING")
                wait = FOLLOWUP_START_TIMEOUT if turn else 6.0
                local = getattr(self, "local_asr", None)
                local_ok = bool(local and local.available())
                last_partial = {"t": 0.0}

                def _on_block(block):
                    nonlocal_last = last_partial
                    if not local_ok:
                        return
                    partial = local.feed(block)
                    now = time.time()
                    if partial and now - nonlocal_last["t"] > 0.4:
                        nonlocal_last["t"] = now
                        self.log(f"[草稿] {partial}")

                if local_ok:
                    local.start()
                pcm, secs, ok = audio.record_utterance(
                    mic,
                    max_seconds=COMMAND_MAX_SECONDS,
                    silence_seconds=COMMAND_SILENCE_SECONDS,
                    start_timeout=wait,
                    on_block=_on_block if local_ok else None,
                    pre_pcm=pre,
                )
                if not ok:
                    self.say("没听到声音。" if turn == 0 else "好，先这样。需要时再叫我。")
                    self._set_state("IDLE")
                    return
                local_result = local.finish(pcm) if local_ok else None
                # 云端识别/云端重听用降噪+AGC 后的音频（本地双遍已在原始流上跑完）
                asr_pcm = enhance_pcm(pcm) or pcm
                text, engine = self._asr(asr_pcm, local_result)
            self.log(f"指令({secs:.1f}s, {engine}): {text!r}")
            if not text:
                self.say("没听清，再说一次。")
                turn += 1
                continue
            if _is_noise(text):
                # 「Yeah。」「嗯。」这类不是指令：不回复、不占对话轮次
                self.log(f"[噪声] 忽略: {text!r}")
                continue
            # 端侧识别出了字、但规则解析不出意图：才花一次云端识别重听（云端为辅）
            if (pcm is not None
                    and getattr(config, "ASR_CLOUD_RETRY_ON_UNKNOWN", True)
                    and self.cloud_asr and str(engine).startswith("local")
                    and parse(text).get("action") == "unknown"):
                cloud_text = ""
                try:
                    cloud_text = (llm.asr_pcm(asr_pcm, SAMPLE_RATE) or "").strip()
                except Exception as exc:
                    self.log(f"[ASR] 云端重听失败: {str(exc)[:120]}")
                if cloud_text and cloud_text != text:
                    # 只有「云端文本能解析出明确意图」时才采纳；否则保留本地结果，
                    # 避免在极低信噪比下云端也听错、反而把本地更好的结果覆盖掉。
                    if parse(cloud_text).get("action") != "unknown":
                        self.log(f"[ASR] 本地文本解析不了，用云端重听: {cloud_text!r}")
                        text, engine = cloud_text, "cloud"
                        self.log(f"指令({secs:.1f}s, {engine}): {text!r}")
                    else:
                        self.log(f"[ASR] 云端重听也没有明确意图，保留本地结果: {cloud_text!r}")
            self._set_state("THINKING")
            reply, should_exit = self.handle(text, history)
            self.say(reply)
            mic.flush()
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply})
            if should_exit:
                self._set_state("IDLE")
                return
            if self._interrupted:
                # 用户插话算「同一轮还没说完」，不消耗对话轮次，立刻接着听
                self.log("[打断] 用户已插话，继续听下一句")
                continue
            turn += 1
        self.say("先聊到这，需要时再叫我。")
        self._set_state("IDLE")


def main():
    parser = argparse.ArgumentParser(description="电脑语音助手")
    parser.add_argument("--text", action="store_true", help="文字模式（键盘输入）")
    parser.add_argument("--dry-run", action="store_true", help="演练模式，不执行危险操作")
    parser.add_argument("--no-hotkey", action="store_true", help="不注册全局热键")
    parser.add_argument("--no-wake", action="store_true", help="只响应热键，不做唤醒词")
    args = parser.parse_args()

    assistant = Assistant(
        text_mode=args.text,
        dry_run=args.dry_run,
        use_hotkey=not args.no_hotkey,
        use_wake=not args.no_wake,
    )
    if args.text:
        assistant.run_text()
    else:
        assistant.run_voice()


if __name__ == "__main__":
    main()
