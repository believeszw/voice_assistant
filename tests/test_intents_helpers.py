"""intents 辅助函数与规则表约定的回归测试。"""

import pytest

from intents import RULES, cn2int, normalize, parse


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0", 0),
        ("50", 50),
        ("五十", 50),
        ("十五", 15),
        ("一百", 100),
        ("一百二十", 120),
        ("两千", 2000),
        ("", None),
        ("abc", None),
    ],
)
def test_cn2int(text, expected):
    assert cn2int(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("小助手，打开记事本！", "小助手打开记事本"),
        ("  音量 调到 三十  ", "音量调到三十"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


def test_rules_are_ordered_and_unique():
    assert len(RULES) >= 30
    assert all(callable(rule) for rule in RULES)
    assert len(set(RULES)) == len(RULES)


@pytest.mark.parametrize("text", ["", "   ", "今天吃啥", "姐"])
def test_unknown_shape(text):
    intent = parse(text)
    assert intent["action"] == "unknown"
    assert intent["raw"] == (text or "").strip()
