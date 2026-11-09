"""纯字符串工具的单元测试（不需要音频/Windows 依赖，CI 直接跑）。"""

from __future__ import annotations

import pytest

from text_utils import is_noise, split_compound, strip_fillers, strip_lead, take_delay


@pytest.mark.parametrize(
    "text,expected",
    [
        ("打开记事本，然后调大音量", ["打开记事本", "调大音量"]),
        ("静音，再显示桌面", ["静音", "显示桌面"]),
        (
            "把音量调到五十，然后等2秒钟之后再把音量调到三十",
            ["把音量调到五十", "等2秒钟之后再把音量调到三十"],
        ),
        ("现在几点了", []),
        ("", []),
    ],
)
def test_split_compound(text, expected):
    assert split_compound(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Yeah。", True),
        ("嗯。", True),
        ("姐", True),
        ("打开记事本", False),
        ("现在几点了？", False),
    ],
)
def test_is_noise(text, expected):
    assert is_noise(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("嗯，帮我打开记事本", "打开记事本"),
        ("那个现在几点了", "现在几点了"),
        ("打开记事本", "打开记事本"),
    ],
)
def test_strip_fillers(text, expected):
    assert strip_fillers(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("的话，你打开记事本", "打开记事本"),
        ("你帮我截个屏", "截个屏"),
        ("打开记事本", "打开记事本"),
    ],
)
def test_strip_lead(text, expected):
    assert strip_lead(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("等2秒钟之后，打开记事本", (2.0, "打开记事本")),
        ("等两分钟后再关机", (120.0, "再关机")),
        ("打开记事本", (0.0, "打开记事本")),
    ],
)
def test_take_delay(text, expected):
    assert take_delay(text) == expected
