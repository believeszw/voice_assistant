"""端侧 NLU：Qwen2.5-1.5B-Instruct（llama.cpp）做本地 function calling。

定位（选型 §5）：云端 LLM 不可用/超时/断网时，仍能把长尾说法解析成结构化意图；
规则解析（intents.py）永远是第一道、最快的路径，本模块是「规则没命中」时的本地兜底。

两种输出约束方式（NLU_LOCAL_TOOL_CALLS 切换，默认 json_schema）：
1. json_schema 约束解码：response_format = {"type": "json_schema", ...}，
   解码阶段就只允许合法 JSON，1.5B 小模型也不容易输出脏格式（默认）；
2. tools + tool_calls：经典 function calling 形态，模型返回 tool_calls 后解析
   arguments，便于和云端 function calling 做同一套验收对比。

安全边界（车载场景防幻觉越权）：
- 动作白名单 = llm.ACTIONS，模型编不出来的动作一律丢弃；
- 槽位校验：volume 0-100、url 补 scheme、应用/文件夹名走 config 别名表；
- 危险动作（shutdown/restart/sleep/lock/close_app）仍由 assistant.execute 的二次确认兜住。

模型目录：models/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf
运行时：tools/llama/llama-server.exe（CPU 预编译包，tools/_fetch_llama.py 下载）
"""

import atexit
import json
import subprocess
import threading
import time
from pathlib import Path

import requests

import config
from llm import ACTIONS
from logging_utils import get_logger

_logger = get_logger("voice_assistant.nlu_local")

_PORT = int(config.NLU_LOCAL_PORT)
_BASE = f"http://127.0.0.1:{_PORT}"
_LOG = Path(config.BASE_DIR) / "tools" / "_llama_server.log"

_proc = None
_lock = threading.Lock()
_ERR = ""
_started_at = 0.0
_LAST = {"mode": "", "ms": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "error": ""}

_SYSTEM = """你是 Windows 电脑语音助手「小助手」的意图解析器。把用户的一句话转成 JSON。
只输出 JSON，不要解释。格式：{"action": "动作"}，需要参数时带 name/value/text/term/url。

可用动作：open_app, close_app, volume_up, volume_down, volume_set, volume_max, volume_get,
mute, unmute, media_play_pause, media_next, media_prev, screenshot, lock, sleep, restart,
shutdown, cancel_shutdown, search, open_url, time, date, system_info, copy_text,
read_clipboard, type_text, show_desktop, open_folder, help, exit, chat, unknown

参数：
- open_app / close_app / open_folder：{"action": "...", "name": "记事本"}
- volume_set：{"action": "volume_set", "value": 30}（0-100 的整数）
- search：{"action": "search", "term": "明天天气"}
- open_url：{"action": "open_url", "url": "https://www.baidu.com"}
- copy_text / type_text：{"action": "...", "text": "要复制或输入的文字"}

判断：
1. 语音识别可能有同音错字，按最合理的意图纠正（「量调大」「音量条大」→ volume_up）。
2. 只有话里明确提到「音量/声音/喇叭/静音」才用音量类动作：说「声音小一点」「大点声」→
   volume_down / volume_up；说了具体数字（如「调到三十」）才用 volume_set；
   「调到最大」→ volume_max。
3. 问「现在几点/几点了/什么时间」→ time；问「今天几号/星期几/什么日期」→ date。
4. 空调温度、车窗、导航等本助手没有的能力 → {"action": "unknown"}，不要硬套成音量动作。
5. 闲聊、知识问答、讲笑话 → {"action": "chat"}。
6. 实在听不出要干什么（包括「现在这个点儿了」这类口语省略）→ {"action": "unknown"}。
只输出 JSON。

示例：
「声音小一点」→ {"action": "volume_down"}
「现在几点了」→ {"action": "time"}
「我有点热，空调开到二十四度」→ {"action": "unknown"}
「讲个笑话」→ {"action": "chat"}"""


def _tool_defs():
    """function calling 的工具清单（JSON Schema）。参数与 _SYSTEM 保持同一套。"""
    no_args = [a for a in sorted(ACTIONS)
               if a not in ("open_app", "close_app", "open_folder", "volume_set",
                            "search", "open_url", "copy_text", "type_text", "unknown")]

    def fn(name, desc, props=None, required=None):
        params = {"type": "object", "properties": props or {}, "additionalProperties": False}
        if required:
            params["required"] = required
        return {"type": "function", "function": {"name": name, "description": desc,
                                                 "parameters": params}}

    tools = [fn(a, f"执行 {a}") for a in no_args]
    tools += [
        fn("open_app", "打开应用",
           {"name": {"type": "string", "description": "应用名，如 记事本/浏览器/微信"}},
           ["name"]),
        fn("close_app", "关闭应用", {"name": {"type": "string", "description": "应用名"}}, ["name"]),
        fn("open_folder", "打开文件夹",
           {"name": {"type": "string", "description": "文件夹名，如 下载/文档/桌面"}},
           ["name"]),
        fn("volume_set", "把音量设成指定值",
           {"value": {"type": "integer", "minimum": 0, "maximum": 100}},
           ["value"]),
        fn("search", "用浏览器搜索", {"term": {"type": "string", "description": "搜索词"}}, ["term"]),
        fn("open_url", "打开网址", {"url": {"type": "string", "description": "网址"}}, ["url"]),
        fn("copy_text", "复制文字到剪贴板", {"text": {"type": "string"}}, ["text"]),
        fn("type_text", "把文字输入到当前窗口", {"text": {"type": "string"}}, ["text"]),
        fn("unknown", "听不出意图"),
    ]
    return tools


_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": sorted(ACTIONS)},
        "name": {"type": "string"},
        "value": {"type": "integer", "minimum": 0, "maximum": 100},
        "text": {"type": "string"},
        "term": {"type": "string"},
        "url": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": False,
}


def available() -> bool:
    exe = Path(config.NLU_LOCAL_SERVER)
    model = Path(config.NLU_LOCAL_DIR) / config.NLU_LOCAL_MODEL
    return exe.exists() and model.exists()


def error() -> str:
    return _ERR


# ------------------------------------------------------------------ 进程管理
def _http_ok(timeout: float = 0.6) -> bool:
    try:
        return requests.get(_BASE + "/health", timeout=timeout).status_code == 200
    except Exception:
        return False


def _ensure_server() -> bool:
    """按需拉起 llama-server；已在跑就直接复用。失败记录 _ERR。"""
    global _proc, _ERR, _started_at
    if _http_ok():
        return True
    with _lock:
        if _http_ok():
            return True
        if not available():
            _ERR = "运行时或模型缺失（tools/llama/llama-server.exe / models/llm/*.gguf）"
            return False
        cmd = [
            str(config.NLU_LOCAL_SERVER),
            "-m", str(Path(config.NLU_LOCAL_DIR) / config.NLU_LOCAL_MODEL),
            "--host", "127.0.0.1", "--port", str(_PORT),
            "-c", "2048", "-t", str(config.NLU_LOCAL_THREADS),
            "-ngl", str(config.NLU_LOCAL_NGL),
            "--log-disable",
        ]
        try:
            _LOG.parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(_LOG, "ab")
            t0 = time.time()
            _proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _started_at = t0
        except Exception as exc:  # pragma: no cover
            _ERR = f"启动失败 {type(exc).__name__}: {str(exc)[:120]}"
            _logger.warning("[NLU] 端侧服务启动失败:", _ERR)
            return False
        deadline = time.time() + config.NLU_LOCAL_START_TIMEOUT
        while time.time() < deadline:
            if _proc.poll() is not None:
                _ERR = f"llama-server 退出码 {_proc.returncode}，见 {_LOG}"
                _logger.info("[NLU]", _ERR)
                return False
            if _http_ok(0.5):
                _logger.info(f"[NLU] 端侧模型已加载（{time.time() - t0:.2f}s，Qwen2.5-1.5B Q4_K_M）")
                return True
            time.sleep(0.2)
        _ERR = f"冷启动超时（>{config.NLU_LOCAL_START_TIMEOUT:.0f}s）"
        _logger.info("[NLU]", _ERR)
        return False


def stop():
    global _proc
    with _lock:
        if _proc is not None and _proc.poll() is None:
            try:
                _proc.terminate()
                _proc.wait(timeout=5)
            except Exception:
                try:
                    _proc.kill()
                except Exception:
                    pass
        _proc = None


atexit.register(stop)


def _warm():
    try:
        if _ensure_server():
            _chat("你好", timeout=config.NLU_LOCAL_TIMEOUT)
    except Exception:
        pass


def warmup_async():
    """后台预热（首次加载 1-4 s，别卡住启动和第一句指令）。"""
    if not available():
        return
    threading.Thread(target=_warm, daemon=True).start()


# ------------------------------------------------------------------ 推理
def _chat(text: str, history=None, timeout: float = None) -> dict:
    """调一次 /v1/chat/completions，返回解析后的 intent；失败抛异常由上层兜底。"""
    messages = [{"role": "system", "content": _SYSTEM}]
    if history:
        messages.extend(history[-4:])
    messages.append({"role": "user", "content": text})
    body = {
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": config.NLU_LOCAL_MAX_TOKENS,
        "cache_prompt": True,
    }
    mode = "tool_calls" if config.NLU_LOCAL_TOOL_CALLS else "json_schema"
    if mode == "tool_calls":
        body["tools"] = _tool_defs()
        body["tool_choice"] = "auto"
    else:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "intent", "strict": True, "schema": _INTENT_SCHEMA},
        }
    t0 = time.time()
    resp = requests.post(_BASE + "/v1/chat/completions", json=body,
                         timeout=timeout or config.NLU_LOCAL_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    ms = (time.time() - t0) * 1000.0
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    timings = data.get("timings") or {}
    _LAST.update({
        "mode": mode,
        "ms": ms,
        "prompt_tokens": int(timings.get("prompt_n") or 0),
        "completion_tokens": int(timings.get("predicted_n") or 0),
        "error": "",
    })
    if mode == "tool_calls" and msg.get("tool_calls"):
        args = msg["tool_calls"][0].get("function", {}).get("arguments") or "{}"
        obj = json.loads(args)
        if "action" not in obj and "name" in obj:
            obj["action"] = msg["tool_calls"][0]["function"].get("name")
        return obj
    content = (msg.get("content") or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content)


def _canon_name(name: str, table) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if name in table:
        return name
    for alias in table:
        if alias and (alias in name or name in alias):
            return alias
    return name


# 音量类动作的语义护栏：1.5B 模型容易把「空调开到二十四度」硬套成 volume_set 24。
# 规则很便宜——没提到声音相关的词，就别让它动音量（车载场景宁可不执行，也不能乱执行）。
_VOLUME_WORDS = ("音量", "声音", "喇叭", "音响", "静音", "声", "响", "音量条")


def _volume_context_ok(text: str) -> bool:
    return any(w in text for w in _VOLUME_WORDS)


def validate(obj: dict, text: str = "") -> dict:
    """白名单 + 槽位边界 + 语义护栏校验；不合法返回 {}。"""
    if not isinstance(obj, dict):
        return {}
    action = str(obj.get("action", "")).strip()
    if action not in ACTIONS or action == "unknown":
        # 允许 chat：闲聊/知识问答交给云端或兜底话术；unknown 交给上层继续兜底
        if action != "chat":
            return {}
    if (action.startswith("volume_") or action in ("mute", "unmute")) and text \
            and not _volume_context_ok(text):
        return {}
    out = {"action": action}
    if action in ("open_app", "close_app"):
        name = _canon_name(obj.get("name", ""), config.APPS)
        if not name:
            return {}
        out["name"] = name
    elif action == "open_folder":
        name = _canon_name(obj.get("name", ""), config.FOLDERS)
        if not name:
            return {}
        out["name"] = name
    elif action == "volume_set":
        try:
            out["value"] = max(0, min(100, int(round(float(obj.get("value"))))))
        except (TypeError, ValueError):
            return {}
    elif action == "search":
        term = str(obj.get("term", "")).strip()
        if not term:
            return {}
        out["term"] = term
    elif action == "open_url":
        url = str(obj.get("url", "")).strip()
        if not url:
            return {}
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        out["url"] = url
    elif action in ("copy_text", "type_text"):
        text = str(obj.get("text", "")).strip()
        if not text:
            return {}
        out["text"] = text
    elif action == "chat":
        # chat 由 assistant 交给云端闲聊/本地兜底话术，不需要槽位
        pass
    out["local"] = True
    out["nlu_ms"] = round(_LAST.get("ms", 0.0), 1)
    return out


def parse(text: str, history=None) -> dict:
    """端侧解析一句话；不可用或失败返回 {}（调用方继续兜底）。"""
    text = (text or "").strip()
    if not text:
        return {}
    if not _ensure_server():
        return {}
    try:
        obj = _chat(text, history)
    except Exception as exc:
        _LAST["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        _logger.warning("[NLU] 端侧解析失败:", _LAST["error"])
        return {}
    intent = validate(obj, text)
    if intent:
        intent["raw"] = text
    return intent


def last_stats() -> dict:
    return dict(_LAST)
