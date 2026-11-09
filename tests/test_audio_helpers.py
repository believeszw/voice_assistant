"""Assistant 的纯逻辑辅助（复合指令拆分、噪声过滤、预录裁剪）。

导入 assistant 需要 Windows 音频/COM 依赖，因此整文件标记 audio 并在非 Windows 跳过；
CI 用 `-m "not audio"` 即可避开。
"""

import sys

import numpy as np
import pytest

pytestmark = [
    pytest.mark.audio,
    pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows"),
]

assistant = pytest.importorskip("assistant")
_take_delay = assistant._take_delay
_strip_fillers = assistant._strip_fillers
_strip_lead = assistant._strip_lead
_is_noise = assistant._is_noise
split_compound = assistant.split_compound


@pytest.mark.parametrize(
    "text,expected",
    [
        ("打开记事本，然后调大音量", ["打开记事本", "调大音量"]),
        ("静音，再显示桌面", ["静音", "显示桌面"]),
        ("把音量调到五十，然后等2秒钟之后再把音量调到三十", ["把音量调到五十", "等2秒钟之后再把音量调到三十"]),
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
    assert _is_noise(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("嗯，帮我打开记事本", "打开记事本"),
        ("那个现在几点了", "现在几点了"),
        ("打开记事本", "打开记事本"),
    ],
)
def test_strip_fillers(text, expected):
    assert _strip_fillers(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("的话，你打开记事本", "打开记事本"),
        ("你帮我截个屏", "截个屏"),
        ("打开记事本", "打开记事本"),
    ],
)
def test_strip_lead(text, expected):
    assert _strip_lead(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("等2秒钟之后，打开记事本", (2.0, "打开记事本")),
        ("等两分钟后再关机", (120.0, "再关机")),
        ("打开记事本", (0.0, "打开记事本")),
    ],
)
def test_take_delay(text, expected):
    assert _take_delay(text) == expected


def test_trim_pre_roll_keeps_speech_onset():
    sr = 16000
    pause = np.zeros(sr // 3, dtype=np.int16)
    tone = (np.sin(np.linspace(0, 200 * np.pi, sr * 2 // 5)) * 3000).astype(np.int16)
    pcm = np.concatenate([pause, tone, pause]).tobytes()

    out = assistant.Assistant._trim_pre_roll(pcm)

    # 应从起音前开始，而不是把开头一起丢掉；长度 ≈ 语音 + 前后余量
    assert 0 < len(out) < len(pcm)
    samples = np.frombuffer(out, dtype=np.int16)
    assert np.max(np.abs(samples)) >= 2000
