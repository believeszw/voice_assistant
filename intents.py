"""把中文口语句子解析成结构化指令。

只做规则解析，不依赖大模型，离线可用、可控。
"""

import re

from config import APPS, FOLDERS, WAKE_WORDS

_PUNCT = re.compile(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()《》<>~·\-—_]+")

_POLITE = ["帮我", "请帮我", "请", "麻烦", "帮忙", "给我", "把", "一下", "一点", "好吗", "行吗", "吧"]

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def normalize(text: str) -> str:
    text = _PUNCT.sub("", text or "")
    return text.lower()


def cn2int(s: str):
    """把“五十”“十五”“一百”这类转成整数；也接受阿拉伯数字。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total, section, number = 0, 0, 0
    units = {"十": 10, "百": 100, "千": 1000}
    for ch in s:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in units:
            unit = units[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
        else:
            return None
    return total + section + number


def _strip_polite(text: str) -> str:
    for word in _POLITE:
        if text.startswith(word):
            text = text[len(word):]
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


def parse(text: str):
    """返回 {'action': str, ...}；无法识别时 action='unknown'。"""
    raw = (text or "").strip()
    t = _strip_polite(normalize(raw))

    # 去掉句首的唤醒词（“小助手打开记事本”）
    for wake in WAKE_WORDS:
        if t.startswith(wake):
            t = t[len(wake):]
            break

    if not t:
        return {"action": "unknown", "raw": raw}

    # --- 系统控制（先匹配，避免被“打开/关闭”吃掉）---
    if "取消关机" in t or "取消重启" in t:
        return {"action": "cancel_shutdown", "raw": raw}
    if t in ("退出", "结束", "再见", "拜拜") or "再见" in t or "结束对话" in t or "退出助手" in t:
        return {"action": "exit", "raw": raw}
    if any(w in t for w in ("停止", "闭嘴", "别说了", "安静", "停下", "不要说了")):
        return {"action": "stop_speaking", "raw": raw}
    if any(w in t for w in ("帮助", "你能做什么", "会什么", "有什么功能", "怎么用")):
        return {"action": "help", "raw": raw}

    if any(w in t for w in ("截屏", "截图", "屏幕截图", "拍个照", "截个图", "截个屏", "截图一下")):
        return {"action": "screenshot", "raw": raw}
    if any(w in t for w in ("锁屏", "锁定电脑", "锁电脑", "锁一下")):
        return {"action": "lock", "raw": raw}
    if any(w in t for w in ("休眠", "睡眠", "待机")):
        return {"action": "sleep", "raw": raw}
    if "重启" in t or "重新启动" in t:
        return {"action": "restart", "raw": raw}
    if "关机" in t:
        return {"action": "shutdown", "raw": raw}

    # --- 静音 ---
    if any(w in t for w in ("取消静音", "解除静音", "恢复声音", "打开声音")):
        return {"action": "unmute", "raw": raw}
    if "静音" in t:
        return {"action": "mute", "raw": raw}

    # --- 音量（复合指令的第二句常省略「音量」，如「然后再调到百分之五十」）---
    _vol_num = r"(\d{1,3}|[零一二两三四五六七八九十百]+)"
    m = re.search(rf"(?:调到|调成|设成|调至|设为|设置到)\s*(?:百分之)?\s*{_vol_num}", t)
    if m:
        value = cn2int(m.group(1))
        if value is not None:
            return {"action": "volume_set", "value": max(0, min(100, value)), "raw": raw}
    if "百分之" in t:
        m = re.search(rf"百分之\s*{_vol_num}", t)
        if m:
            value = cn2int(m.group(1))
            if value is not None:
                return {"action": "volume_set", "value": max(0, min(100, value)), "raw": raw}

    # --- 音量 ---
    if any(w in t for w in ("音量", "声音", "声儿")):
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
                return {"action": "volume_set", "value": max(0, min(100, value)), "raw": raw}
        if any(w in t for w in ("大", "增", "高", "响")):
            return {"action": "volume_up", "raw": raw}
        if any(w in t for w in ("小", "减", "低", "轻")):
            return {"action": "volume_down", "raw": raw}
        return {"action": "volume_get", "raw": raw}

    # --- 媒体 ---
    if any(w in t for w in ("下一首", "下一曲", "切歌", "换一首")):
        return {"action": "media_next", "raw": raw}
    if any(w in t for w in ("上一首", "上一曲", "前一首")):
        return {"action": "media_prev", "raw": raw}
    if any(w in t for w in ("播放", "暂停", "继续", "放歌", "停一下音乐")):
        return {"action": "media_play_pause", "raw": raw}

    # --- 亮度 ---
    if "亮度" in t or "屏幕亮" in t:
        if any(w in t for w in ("低", "暗", "降")):
            return {"action": "brightness", "delta": -10, "raw": raw}
        return {"action": "brightness", "delta": 10, "raw": raw}

    # --- 时间 / 日期 / 系统信息 ---
    if any(w in t for w in ("几点", "时间", "什么时候")):
        return {"action": "time", "raw": raw}
    if any(w in t for w in ("几号", "日期", "星期几", "周几", "今天星期", "今天几号")):
        return {"action": "date", "raw": raw}
    if any(w in t for w in ("内存", "cpu", "电池", "磁盘", "硬盘", "配置")):
        return {"action": "system_info", "raw": raw}

    # --- 桌面 ---
    if any(w in t for w in ("显示桌面", "回到桌面", "最小化所有", "最小化")):
        return {"action": "show_desktop", "raw": raw}

    # --- 剪贴板 / 输入 ---
    if "剪贴板" in t and not t.startswith("复制"):
        return {"action": "read_clipboard", "raw": raw}
    if t.startswith("复制") or t.startswith("拷贝"):
        return {"action": "copy_text", "text": _strip_polite(raw)[2:].strip(), "raw": raw}
    if any(t.startswith(w) for w in ("输入", "打字", "键入", "写")):
        keyword = next(w for w in ("输入", "打字", "键入", "写") if t.startswith(w))
        return {"action": "type_text", "text": _strip_polite(raw)[len(keyword):].strip(), "raw": raw}

    # --- 文件夹里的具体文件：「打开桌面的新建文本」 ---
    m = re.match(r"^(?:打开|开)?(桌面|下载|文档|图片|音乐|视频)(?:上|里|中)?的?(.+)$", t)
    if m:
        item = m.group(2).strip("。.!！?？ ")
        if item and item not in ("文件夹", "目录", "窗口", "文件"):
            return {"action": "open_item", "folder": m.group(1), "name": item, "raw": raw}

    # --- 文件夹 ---
    if t.startswith(("打开", "开")):
        folder = _match_folder(t)
        if folder:
            return {"action": "open_folder", "name": folder, "raw": raw}

    # --- 关闭应用 ---
    for verb in ("关闭", "关掉", "退出"):
        if t.startswith(verb):
            app = _match_app(t) or _strip_polite(raw)[len(verb):].strip()
            if app:
                return {"action": "close_app", "name": app, "raw": raw}

    # --- 打开应用 ---
    for verb in ("打开新的", "新建", "新开", "打开", "启动", "运行", "调出", "开"):
        if t.startswith(verb) and len(t) > len(verb):
            rest = _strip_polite(raw)[len(verb):].strip()
            rest = re.sub(r"[，。！？、,.!?；;：:\s]+$", "", rest)
            rest = re.sub(r"^(一个|一台|一份)", "", rest)
            rest = re.sub(r"(一下|吧|啊|呢)$", "", rest)
            app = _match_app(rest) or rest
            if app:
                return {"action": "open_app", "name": app, "raw": raw}

    # --- 搜索 / 网页 ---
    for verb in ("搜索", "搜一下", "搜", "查一下", "查", "百度一下", "百度", "谷歌一下", "谷歌"):
        if t.startswith(verb):
            term = _strip_polite(raw)[len(verb):].strip()
            term = re.sub(r"^(一下|下)", "", term)
            if term:
                return {"action": "search", "term": term, "raw": raw}
    if "网页" in t or "网站" in t:
        return {"action": "open_url", "url": "https://www.baidu.com", "raw": raw}

    if any(w in t for w in ("你好", "在吗", "hello", "嗨")):
        return {"action": "greet", "raw": raw}

    return {"action": "unknown", "raw": raw}
