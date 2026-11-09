"""文本层的纯函数：噪声判断、口头词剥离、复合指令拆分、等待时间解析、应用名白名单。

这些函数只处理字符串，不依赖音频、网络或 Windows API，因此可以在任何环境
（包括只有 pytest/ruff 的 CI）里直接单测。`assistant.py` 用它们把 ASR 的原始
文本整理成意图解析器能吃的指令。
"""

from __future__ import annotations

import re

from intents import cn2int

__all__ = [
    "is_noise",
    "is_safe_app_name",
    "split_compound",
    "strip_fillers",
    "strip_lead",
    "take_delay",
]

# 一句话里的多个指令：「打开记事本，然后调大音量」「静音，再截个屏」
COMPOUND_SPLIT = re.compile(r"[，,；;]\s*(?:然后|接着|再|并且|并)?|然后|接着|并且")

# 拆分后子句开头的连接词：「再调到百分之五十」这种省略主语的补充指令
CLAUSE_PREFIX = re.compile(r"^(?:再|然后|接着|并且|并|之后)\s*")

# 识别器偶尔会把环境音/口头词吐成「Yeah。」「嗯。」这类东西。它们既不是指令，
# 也不该触发闲聊——否则一次演示会被这种噪声吃掉一轮对话额度。
NOISE_STRIP = re.compile(r"[\s，。,.!?！？、；;：:…~～\"'“”‘’()（）\[\]【】]+")
NOISE_WORDS = {
    "yeah",
    "yes",
    "yep",
    "ok",
    "okay",
    "hi",
    "hello",
    "hey",
    "fine",
    "thanks",
    "thank",
    "thankyou",
    "you",
    "i",
    "嗯",
    "啊",
    "哦",
    "呃",
    "唔",
    "诶",
    "哎",
    "唉",
    "呀",
    "哈",
    "呵",
    "嘿",
    "那个",
    "这个",
    "好的",
}

# 口语句首的填充词：「嗯，帮我打开记事本」「那个，现在几点了」
FILLER_PREFIX = re.compile(
    r"^(?:(?:嗯|呃|啊|哦|诶|哎|唉|唔|那个|这个|就是|然后|喂|你好|您好|"
    r"小朋友|小助手|在吗|请|麻烦|帮我)\s*[，,。.！!？?、]?\s*)+"
)

# 子句开头常被 ASR 带上来的口水话/代词：「的话，你打开记事本」「你帮我…」
LEAD_NOISE = re.compile(
    r"^(?:(?:的话|那么|那个|这个|就是|然后|所以|但是|不过|你|您|我|我们|咱们|"
    r"帮我|请|麻烦|先|就)\s*[，,。.！!？?、]?\s*)+"
)

# 复合指令里的「等2秒钟之后」——演示里会拿它验证按序执行
DELAY_RE = re.compile(
    r"^(?:等|等待|过|停)\s*([0-9零一二两三四五六七八九十百]+)\s*"
    r"(秒钟|秒|分钟|分)\s*(?:之后|以后|后)?\s*[，,。.]?\s*"
)

# 允许的启动目标字符：字母数字、常见路径符号、中文；拦掉 cmd 元字符（& | > < ^ % 等）
SAFE_TARGET = re.compile(r"^[A-Za-z0-9_\-./:\\ \u4e00-\u9fff]{1,80}$")


def is_noise(text: str) -> bool:
    """判断识别结果是不是「非指令的噪声」：纯标点、单字、口头词。"""
    t = NOISE_STRIP.sub("", text or "").strip().lower()
    if len(t) <= 1:
        return True
    return t in NOISE_WORDS


def is_safe_app_name(name: str) -> bool:
    """ASR 文本要交给 `cmd /c start` 前，先过字符白名单，避免命令注入。"""
    return bool(SAFE_TARGET.match((name or "").strip()))


def strip_fillers(text: str) -> str:
    """去掉句首口头词/连接词，返回真正像指令的部分。"""
    prev = None
    t = (text or "").strip()
    while prev != t:
        prev = t
        t = FILLER_PREFIX.sub("", t).strip("，,。.！!？?、 ")
    return t


def strip_lead(text: str) -> str:
    """去掉子句开头的「的话，你」这类残留，便于规则解析。"""
    t = (text or "").strip()
    prev = None
    while prev != t:
        prev = t
        t = LEAD_NOISE.sub("", t).strip("，,。.！!？?、 ")
    return t


def take_delay(text: str) -> tuple[float, str]:
    """取出开头的等待时间，返回 (秒数或 0, 剩余文本)。"""
    m = DELAY_RE.match(text or "")
    if not m:
        return 0.0, text
    value = cn2int(m.group(1))
    if value is None:
        return 0.0, text
    unit = 60 if "分" in m.group(2) else 1
    return float(value * unit), text[m.end() :].strip()


def split_compound(text: str) -> list[str]:
    """把复合指令拆成子句；不足两句返回空列表（走单指令逻辑）。

    拆分后剥掉开头连接词（「再/然后/接着/并且」），这样第二句可以是
    「再调到百分之五十」这种省略主语的补充指令。
    """
    raw = [p.strip("，,；; 。.!！?？、") for p in COMPOUND_SPLIT.split(text or "")]
    parts = []
    for p in raw:
        p = CLAUSE_PREFIX.sub("", p).strip()
        if p:
            parts.append(p)
    return parts if len(parts) > 1 else []
