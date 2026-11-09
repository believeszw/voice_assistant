"""把中文口语句子解析成结构化指令。

只做规则解析，不依赖大模型，离线可用、可控。

规则按 :data:`RULES` 列表顺序依次尝试，第一个命中的规则生效。
新增说法时把规则插到正确的优先级位置，并在 ``tests/test_intents.py`` 补一条 golden 用例，
避免规则顺序变化导致已有说法被别的规则抢走。
"""

import re
from collections.abc import Callable

from config import APPS, FOLDERS, WAKE_WORDS

Intent = dict
Rule = Callable[[str, str], Intent | None]

#: 句子归一化时去掉的标点/空白。
_PUNCT = re.compile(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()《》<>~·\-—_]+")

#: 句首礼貌词，按长度从长到短剥离（顺序保留原实现）。
_POLITE = ["帮我", "请帮我", "请", "麻烦", "帮忙", "给我", "把", "一下", "一点", "好吗", "行吗", "吧"]

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}

#: 音量数字：阿拉伯数字 1~3 位，或中文数字。
_VOL_NUM = r"(\d{1,3}|[零一二两三四五六七八九十百]+)"

_APP_VERBS = ("打开新的", "新建", "新开", "打开", "启动", "运行", "调出", "开")
_CLOSE_VERBS = ("关闭", "关掉", "退出")
_SEARCH_VERBS = ("搜索", "搜一下", "搜", "查一下", "查", "百度一下", "百度", "谷歌一下", "谷歌")
_TYPE_VERBS = ("输入", "打字", "键入", "写")


def normalize(text: str) -> str:
    """去掉标点与空白并转小写，得到规则匹配用的句子。"""
    text = _PUNCT.sub("", text or "")
    return text.lower()


def cn2int(s: str) -> int | None:
    """把“五十”“十五”“一百”这类转成整数；也接受阿拉伯数字；无法解析返回 None。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    section, number = 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
        else:
            return None
    return section + number


def _strip_polite(text: str) -> str:
    for word in _POLITE:
        if text.startswith(word):
            text = text[len(word) :]
    return text


def _match_app(text: str):
    for name in sorted(APPS, key=len, reverse=True):
        if name and name in text:
            return name
    return None


def _match_folder(text: str):
    for name in sorted(FOLDERS, key=len, reverse=True):
        if name in text:
            return name
    return None


def _volume_intent(action: str, raw: str, value: int | None = None) -> Intent:
    intent = {"action": action, "raw": raw}
    if value is not None:
        intent["value"] = max(0, min(100, value))
    return intent


# ---------------------------------------------------------------------------
# 规则实现：每个函数接收 (归一化句子 t, 原始句子 raw)，命中返回 intent，否则返回 None。
# 顺序与重构前的 if 链一致，改动顺序前先跑 tests/test_intents.py。
# ---------------------------------------------------------------------------


def _rule_browser_search(t: str, raw: str) -> Intent | None:
    """「用/打开 谷歌浏览器 搜索 X」——指定浏览器搜索。"""
    m = re.match(
        r"^(?:用|打开|使用|拿)?(谷歌浏览器|谷歌|chrome|Chrome|edge|Edge)(?:浏览器)?"
        r"(?:搜索|搜一下|搜|查一下|查|百度一下)(.+)$",
        t,
    )
    if not m:
        return None
    browser = "edge" if m.group(1).lower() == "edge" else "chrome"
    term = _strip_polite(m.group(2)).strip()
    term = re.sub(r"^(一下|下)", "", term).strip()
    if not term:
        return None
    return {"action": "search", "term": term, "browser": browser, "raw": raw}


def _rule_cancel_shutdown(t: str, raw: str) -> Intent | None:
    if "取消关机" in t or "取消重启" in t:
        return {"action": "cancel_shutdown", "raw": raw}
    return None


def _rule_exit(t: str, raw: str) -> Intent | None:
    if t in ("退出", "结束", "再见", "拜拜") or "再见" in t or "结束对话" in t or "退出助手" in t:
        return {"action": "exit", "raw": raw}
    return None


def _rule_stop_speaking(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("停止", "闭嘴", "别说了", "安静", "停下", "不要说了")):
        return {"action": "stop_speaking", "raw": raw}
    return None


def _rule_help(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("帮助", "你能做什么", "会什么", "有什么功能", "怎么用")):
        return {"action": "help", "raw": raw}
    return None


def _rule_screenshot(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("截屏", "截图", "屏幕截图", "拍个照", "截个图", "截个屏", "截图一下")):
        return {"action": "screenshot", "raw": raw}
    return None


def _rule_lock(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("锁屏", "锁定电脑", "锁电脑", "锁一下")):
        return {"action": "lock", "raw": raw}
    return None


def _rule_sleep(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("休眠", "睡眠", "待机")):
        return {"action": "sleep", "raw": raw}
    return None


def _rule_restart(t: str, raw: str) -> Intent | None:
    if "重启" in t or "重新启动" in t:
        return {"action": "restart", "raw": raw}
    return None


def _rule_shutdown(t: str, raw: str) -> Intent | None:
    if "关机" in t:
        return {"action": "shutdown", "raw": raw}
    return None


def _rule_unmute(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("取消静音", "解除静音", "恢复声音", "打开声音")):
        return {"action": "unmute", "raw": raw}
    return None


def _rule_mute(t: str, raw: str) -> Intent | None:
    if "静音" in t:
        return {"action": "mute", "raw": raw}
    return None


def _rule_volume_set_compact(t: str, raw: str) -> Intent | None:
    """省略“音量”二字的绝对音量，如「转到/调到百分之五十」。"""
    m = re.search(rf"(?:调到|调成|设成|调至|设为|设置到)\s*(?:百分之)?\s*{_VOL_NUM}", t)
    if not m:
        return None
    value = cn2int(m.group(1))
    if value is None:
        return None
    return _volume_intent("volume_set", raw, value)


def _rule_volume_set_percent(t: str, raw: str) -> Intent | None:
    """「百分之五十」形式的绝对音量。"""
    if "百分之" not in t:
        return None
    m = re.search(rf"百分之\s*{_VOL_NUM}", t)
    if not m:
        return None
    value = cn2int(m.group(1))
    if value is None:
        return None
    return _volume_intent("volume_set", raw, value)


def _rule_volume_keyword(t: str, raw: str) -> Intent | None:
    """带“音量/声音/声儿”的查询、静音、最大、绝对设置、调大/调小。"""
    if not any(w in t for w in ("音量", "声音", "声儿")):
        return None
    if "取消静音" in t or "恢复声音" in t or "打开声音" in t:
        return {"action": "unmute", "raw": raw}
    if "静音" in t:
        return {"action": "mute", "raw": raw}
    if "最大" in t:
        return {"action": "volume_max", "raw": raw}
    # 只有“调到/设为/音量+数字”才当成绝对音量，避免“调大一点”里的“一”被误识别
    m = re.search(r"(?:调到|设为|设置到|音量到|音量)(\d{1,3}|[零一二两三四五六七八九十百]+)", t)
    if m:
        value = cn2int(m.group(1))
        if value is not None:
            return _volume_intent("volume_set", raw, value)
    if any(w in t for w in ("大", "增", "高", "响")):
        return {"action": "volume_up", "raw": raw}
    if any(w in t for w in ("小", "减", "低", "轻")):
        return {"action": "volume_down", "raw": raw}
    return {"action": "volume_get", "raw": raw}


def _rule_media_next(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("下一首", "下一曲", "切歌", "换一首")):
        return {"action": "media_next", "raw": raw}
    return None


def _rule_media_prev(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("上一首", "上一曲", "前一首")):
        return {"action": "media_prev", "raw": raw}
    return None


def _rule_media_play_pause(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("播放", "暂停", "继续", "放歌", "停一下音乐")):
        return {"action": "media_play_pause", "raw": raw}
    return None


def _rule_brightness(t: str, raw: str) -> Intent | None:
    if not ("亮度" in t or "屏幕亮" in t):
        return None
    delta = -10 if any(w in t for w in ("低", "暗", "降")) else 10
    return {"action": "brightness", "delta": delta, "raw": raw}


def _rule_time(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("几点", "时间", "什么时候")):
        return {"action": "time", "raw": raw}
    return None


def _rule_date(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("几号", "日期", "星期几", "周几", "今天星期", "今天几号")):
        return {"action": "date", "raw": raw}
    return None


def _rule_system_info(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("内存", "cpu", "电池", "磁盘", "硬盘", "配置")):
        return {"action": "system_info", "raw": raw}
    return None


def _rule_show_desktop(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("显示桌面", "回到桌面", "最小化所有", "最小化")):
        return {"action": "show_desktop", "raw": raw}
    return None


def _rule_read_clipboard(t: str, raw: str) -> Intent | None:
    if "剪贴板" in t and not t.startswith("复制"):
        return {"action": "read_clipboard", "raw": raw}
    return None


def _rule_copy_text(t: str, raw: str) -> Intent | None:
    if not (t.startswith("复制") or t.startswith("拷贝")):
        return None
    return {"action": "copy_text", "text": _strip_polite(raw)[2:].strip(), "raw": raw}


def _rule_type_text(t: str, raw: str) -> Intent | None:
    keyword = next((w for w in _TYPE_VERBS if t.startswith(w)), None)
    if not keyword:
        return None
    return {"action": "type_text", "text": _strip_polite(raw)[len(keyword) :].strip(), "raw": raw}


def _rule_open_item(t: str, raw: str) -> Intent | None:
    m = re.match(r"^(?:打开|开)?(桌面|下载|文档|图片|音乐|视频)(?:上|里|中)?的?(.+)$", t)
    if not m:
        return None
    item = m.group(2).strip("。.!！?？ ")
    if not item or item in ("文件夹", "目录", "窗口", "文件"):
        return None
    return {"action": "open_item", "folder": m.group(1), "name": item, "raw": raw}


def _rule_open_folder(t: str, raw: str) -> Intent | None:
    if not t.startswith(("打开", "开")):
        return None
    folder = _match_folder(t)
    if not folder:
        return None
    return {"action": "open_folder", "name": folder, "raw": raw}


def _rule_close_app(t: str, raw: str) -> Intent | None:
    verb = next((v for v in _CLOSE_VERBS if t.startswith(v)), None)
    if not verb:
        return None
    app = _match_app(t) or _strip_polite(raw)[len(verb) :].strip()
    if not app:
        return None
    return {"action": "close_app", "name": app, "raw": raw}


def _rule_open_app(t: str, raw: str) -> Intent | None:
    for verb in _APP_VERBS:
        if not (t.startswith(verb) and len(t) > len(verb)):
            continue
        rest = _strip_polite(raw)[len(verb) :].strip()
        rest = re.sub(r"[，。！？、,.!?；;：:\s]+$", "", rest)
        rest = re.sub(r"^(一个|一台|一份)", "", rest)
        rest = re.sub(r"(一下|吧|啊|呢)$", "", rest)
        app = _match_app(rest) or rest
        if app:
            return {"action": "open_app", "name": app, "raw": raw}
    return None


def _rule_search(t: str, raw: str) -> Intent | None:
    browser = ""
    for tag, name in (
        ("谷歌浏览器", "chrome"),
        ("chrome", "chrome"),
        ("Chrome", "chrome"),
        ("谷歌", "chrome"),
        ("edge", "edge"),
        ("Edge", "edge"),
    ):
        if tag in raw:
            browser = name
            break
    verb = next((v for v in _SEARCH_VERBS if t.startswith(v)), None)
    if not verb:
        return None
    term = _strip_polite(raw)[len(verb) :].strip()
    term = re.sub(r"^(一下|下)", "", term)
    term = re.sub(r"^(用)?(谷歌浏览器|谷歌|chrome|Chrome|edge|Edge)", "", term).strip()
    if not term:
        return None
    intent = {"action": "search", "term": term, "raw": raw}
    if browser:
        intent["browser"] = browser
    return intent


def _rule_open_url(t: str, raw: str) -> Intent | None:
    if "网页" in t or "网站" in t:
        return {"action": "open_url", "url": "https://www.baidu.com", "raw": raw}
    return None


def _rule_greet(t: str, raw: str) -> Intent | None:
    if any(w in t for w in ("你好", "在吗", "hello", "嗨")):
        return {"action": "greet", "raw": raw}
    return None


#: 规则表：顺序即优先级；调换顺序会改变已有说法的解析结果。
RULES: tuple[Rule, ...] = (
    _rule_browser_search,
    _rule_cancel_shutdown,
    _rule_exit,
    _rule_stop_speaking,
    _rule_help,
    _rule_screenshot,
    _rule_lock,
    _rule_sleep,
    _rule_restart,
    _rule_shutdown,
    _rule_unmute,
    _rule_mute,
    _rule_volume_set_compact,
    _rule_volume_set_percent,
    _rule_volume_keyword,
    _rule_media_next,
    _rule_media_prev,
    _rule_media_play_pause,
    _rule_brightness,
    _rule_time,
    _rule_date,
    _rule_system_info,
    _rule_show_desktop,
    _rule_read_clipboard,
    _rule_copy_text,
    _rule_type_text,
    _rule_open_item,
    _rule_open_folder,
    _rule_close_app,
    _rule_open_app,
    _rule_search,
    _rule_open_url,
    _rule_greet,
)


def parse(text: str) -> Intent:
    """返回 {'action': str, ...}；无法识别时 action='unknown'。"""
    raw = (text or "").strip()
    t = _strip_polite(normalize(raw))

    # 去掉句首的唤醒词（“小助手打开记事本”）
    for wake in WAKE_WORDS:
        if t.startswith(wake):
            t = t[len(wake) :]
            break

    if not t:
        return {"action": "unknown", "raw": raw}

    for rule in RULES:
        intent = rule(t, raw)
        if intent:
            return intent
    return {"action": "unknown", "raw": raw}
