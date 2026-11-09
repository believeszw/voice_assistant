"""llm.py 的纯逻辑辅助函数测试：不联网，也不写真实凭据。"""

import io
import wave

import pytest

pytest.importorskip("requests")  # llm 模块顶层依赖 requests
llm = pytest.importorskip("llm")


def test_pcm_to_wav_roundtrip():
    pcm = b"\x01\x02" * 160
    data = llm.pcm_to_wav(pcm, rate=16000, channels=1)
    assert data[:4] == b"RIFF"
    with wave.open(io.BytesIO(data), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.readframes(wf.getnframes()) == pcm


def test_message_text_strips_content():
    data = {"choices": [{"message": {"content": "  你好  "}}]}
    assert llm._message_text(data) == "你好"


@pytest.mark.parametrize(
    "data",
    [{}, {"choices": []}, {"choices": [{}]}, {"choices": "not-a-list"}],
)
def test_message_text_tolerates_bad_payload(data):
    assert llm._message_text(data) == ""


def _reset_key_cache(monkeypatch):
    monkeypatch.setattr(llm, "_KEY", None)
    monkeypatch.setattr(llm, "_KEY_LOADED", False)


def test_available_uses_env_key(monkeypatch):
    monkeypatch.setenv("XIAOMI_API_KEY", "test-key")
    monkeypatch.delenv("VOICE_OFFLINE", raising=False)
    _reset_key_cache(monkeypatch)
    assert llm.available() is True


def test_available_false_when_offline(monkeypatch):
    monkeypatch.setenv("XIAOMI_API_KEY", "test-key")
    monkeypatch.setenv("VOICE_OFFLINE", "1")
    _reset_key_cache(monkeypatch)
    assert llm.available() is False
