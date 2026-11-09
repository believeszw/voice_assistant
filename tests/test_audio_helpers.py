"""Assistant 的音频相关辅助测试（预录裁剪需要 numpy，整文件标记 audio）。

纯字符串工具的用例已移到 test_text_utils.py，CI 无需音频依赖即可覆盖。
"""

import sys

import pytest

pytestmark = [
    pytest.mark.audio,
    pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows"),
]

# CI 只装 requirements-dev（pytest/ruff），运行依赖按需跳过，不阻塞收集
assistant = pytest.importorskip("assistant")
np = pytest.importorskip("numpy")


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
