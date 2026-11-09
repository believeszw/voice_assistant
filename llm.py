"""小米 MiMo 云端能力：语音识别（ASR）、语音合成（TTS）、意图理解与闲聊。

MiMo 的 ASR/TTS 走的是 chat/completions 方言：
- ASR：messages[0].content = [{"type": "input_audio",
       "input_audio": {"data": "data:audio/wav;base64,..."}}]
- TTS：messages = [user 风格指令, assistant 待读文本]，audio={"voice": ..., "format": "wav"}
         响应 choices[0].message.audio.data 是 base64 的 wav

密钥来源（不写进项目文件）：环境变量 XIAOMI_API_KEY / MIMO_API_KEY，
否则读 DSH 的凭据文件 C:\\Users\\Administrator\\.dsh\\.credentials.yaml 的 refs.XIAOMI_API_KEY。
"""

import base64
import io
import json
import os
import re
import wave
from pathlib import Path

import requests

CRED_FILE = (
    Path(os.environ.get("DSH_CREDENTIALS", ""))
    if os.environ.get("DSH_CREDENTIALS")
    else (Path.home() / ".dsh" / ".credentials.yaml")
)

BASE_URL = os.environ.get("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
ASR_MODEL = os.environ.get("MIMO_ASR_MODEL", "mimo-v2.5-asr")
TTS_MODEL = os.environ.get("MIMO_TTS_MODEL", "mimo-v2.5-tts")
LLM_MODEL = os.environ.get("MIMO_LLM_MODEL", "mimo-v2.6-flash")
TTS_VOICE = os.environ.get("MIMO_TTS_VOICE", "冰糖")
TTS_STYLE = os.environ.get("MIMO_TTS_STYLE", "语速稍快，语气自然")

_KEY = None
_KEY_LOADED = False


def _load_key() -> str:
    for name in ("XIAOMI_API_KEY", "MIMO_API_KEY"):
        val = os.environ.get(name)
        if val:
            return val.strip()
    try:
        text = CRED_FILE.read_text(encoding="utf-8")
    except Exception:
        return ""
    m = re.search(r"XIAOMI_API_KEY:\s*(\S+)", text)
    return m.group(1).strip() if m else ""


def key() -> str:
    global _KEY, _KEY_LOADED
    if not _KEY_LOADED:
        _KEY = _load_key()
        _KEY_LOADED = True
    return _KEY or ""


def available() -> bool:
    if os.environ.get("VOICE_OFFLINE") == "1":
        return False
    return bool(key())


def _post(body: dict, timeout=(5, 45)) -> dict:
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _message_text(data: dict) -> str:
    try:
        return (data["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


# ---------------------------------------------------------------- ASR / TTS
def pcm_to_wav(pcm: bytes, rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def asr_wav(wav_bytes: bytes, language: str = "zh") -> str:
    """wav 字节 → 文本。"""
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    body = {
        "model": ASR_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": f"data:audio/wav;base64,{b64}"},
                    }
                ],
            }
        ],
        "asr_options": {"language": language},
    }
    return _message_text(_post(body, timeout=(5, 60)))


def asr_pcm(pcm: bytes, rate: int = 16000, language: str = "zh") -> str:
    return asr_wav(pcm_to_wav(pcm, rate), language=language)


def tts_wav(text: str, voice: str = "", style: str = "", timeout: float = None) -> bytes:
    """文本 → wav 字节。timeout：整段合成的读超时（秒），由 TTS 双路按首包预算传入。"""
    body = {
        "model": TTS_MODEL,
        "messages": [
            {"role": "user", "content": style or TTS_STYLE},
            {"role": "assistant", "content": text},
        ],
        "audio": {"voice": voice or TTS_VOICE, "format": "wav"},
    }
    data = _post(body, timeout=(5, timeout) if timeout else (5, 120))
    try:
        audio = data["choices"][0]["message"].get("audio") or {}
        b64 = audio.get("data")
    except (KeyError, IndexError, TypeError):
        return b""
    return base64.b64decode(b64) if b64 else b""


# ---------------------------------------------------------------- LLM
ACTIONS = {
    "open_app",
    "close_app",
    "volume_up",
    "volume_down",
    "volume_set",
    "volume_max",
    "volume_get",
    "mute",
    "unmute",
    "media_play_pause",
    "media_next",
    "media_prev",
    "screenshot",
    "lock",
    "sleep",
    "restart",
    "shutdown",
    "cancel_shutdown",
    "search",
    "open_url",
    "time",
    "date",
    "system_info",
    "copy_text",
    "read_clipboard",
    "type_text",
    "show_desktop",
    "open_folder",
    "help",
    "exit",
    "chat",
    "unknown",
}

INTENT_SYSTEM = """你是电脑语音助手的意图解析器。把用户说的一句话解析成一个 JSON，只输出 JSON，不要解释、不要 Markdown。
格式：{"action": "动作"}，需要参数时带上：
- "name"：应用名或文件夹名
- "value"：音量 0-100
- "text"：要复制或输入的文字
- "term"：搜索词
- "url"：网址

可用动作：
open_app, close_app, volume_up, volume_down, volume_set, volume_max, volume_get,
mute, unmute, media_play_pause, media_next, media_prev, screenshot, lock, sleep,
restart, shutdown, cancel_shutdown, search, open_url, time, date, system_info,
copy_text, read_clipboard, type_text, show_desktop, open_folder, help, exit, chat, unknown

判断要点：
1. 语音识别可能有同音错字，按最合理的意图纠正。比如「浪大」「老大」「拉大」「两条大」「量调大」都是把音量调大 → volume_up；「小一点」「声音小」→ volume_down。
2. 打开应用/文件 → open_app（name 用中文原名，如 记事本、微信、浏览器）。
3. 关闭应用 → close_app。
4. 搜索/查资料 → search；打开网址 → open_url。
5. 闲聊、提问、问"今天吃啥/你叫什么/讲个笑话"、或没法归到上面动作 → chat。
6. 实在听不出要干什么 → unknown。

只输出 JSON。"""


def understand(text: str, history=None) -> dict:
    """把一句话解析成意图 dict；失败返回 {"action": "unknown"}。"""
    messages = [{"role": "system", "content": INTENT_SYSTEM}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": text})
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 120,
        "thinking": {"type": "disabled"},
    }
    try:
        content = _message_text(_post(body, timeout=(5, 30)))
    except Exception:
        return {"action": "unknown"}
    content = content.strip().strip("`")
    if content.startswith("json"):
        content = content[4:].strip()
    try:
        data = json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return {"action": "unknown"}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {"action": "unknown"}
    if not isinstance(data, dict):
        return {"action": "unknown"}
    action = str(data.get("action", "unknown")).strip()
    if action not in ACTIONS:
        return {"action": "unknown"}
    out = {"action": action, "raw": text, "llm": True}
    for field in ("name", "text", "term", "url"):
        if isinstance(data.get(field), str) and data[field].strip():
            out[field] = data[field].strip()
    if "value" in data:
        try:
            out["value"] = max(0, min(100, int(float(data["value"]))))
        except (TypeError, ValueError):
            pass
    return out


CHAT_SYSTEM = """你是运行在 Windows 电脑上的中文语音助手「小助手」。
要求：
- 用口语回答，简短，通常一到两句话，不要用 Markdown、列表、表情符号。
- 你可以控制电脑：打开/关闭应用、调音量、截屏、锁屏、查时间日期、看内存、搜索网页、复制输入文字等。
- 如果用户问你能做什么，用一句话概括并举两三个例子。
- 如果用户的要求超出能力范围，直接说明做不到，并给出可替代的建议。
- 用户的话可能是语音识别错了（例如「今天」被听成「丁先」）。句子明显不通时不要硬猜，用一句话请对方再说一遍或确认意思。
- 回答里不要念出代码、路径或链接。
- 你没有任何工具可以调用，不要输出工具调用语法（如 toolcall/function），直接说话回答。"""


def chat_reply(text: str, history=None) -> str:
    messages = [{"role": "system", "content": CHAT_SYSTEM}]
    if history:
        messages.extend(history[-8:])
    messages.append({"role": "user", "content": text})
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 200,
        "thinking": {"type": "disabled"},
    }
    try:
        reply = _message_text(_post(body, timeout=(5, 40)))
    except Exception:
        return ""
    # 模型偶尔会输出工具调用语法（本产品没有工具调用，直接丢掉整段）
    if "<toolcall" in reply or "<tool_call" in reply or "function=" in reply:
        return "这个我还答不上来，换个说法再试试？"
    reply = re.sub(r"[*_#>`]+", "", reply).strip()
    return reply or "这个我还答不上来，换个说法再试试？"
