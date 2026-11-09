"""Vosk 离线语音识别封装。"""

import json
import wave

import vosk

from config import MODEL_DIR, SAMPLE_RATE

_model = None


def get_model():
    global _model
    if _model is None:
        if not MODEL_DIR.exists():
            raise RuntimeError(f"找不到 Vosk 模型: {MODEL_DIR}")
        vosk.SetLogLevel(-1)
        _model = vosk.Model(str(MODEL_DIR))
    return _model


def transcribe_pcm(pcm: bytes) -> str:
    rec = vosk.KaldiRecognizer(get_model(), SAMPLE_RATE)
    rec.AcceptWaveform(pcm)
    text = json.loads(rec.FinalResult()).get("text", "")
    return "".join(text.split())


def transcribe_wav(path: str) -> str:
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1 and wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE, "wav 必须是 16k/16bit/单声道"
        pcm = wf.readframes(wf.getnframes())
    return transcribe_pcm(pcm)


class StreamASR:
    """流式识别：用来做唤醒词检测。"""

    def __init__(self):
        self.rec = vosk.KaldiRecognizer(get_model(), SAMPLE_RATE)

    def accept(self, block: bytes):
        if self.rec.AcceptWaveform(block):
            text = json.loads(self.rec.Result()).get("text", "")
            return "".join(text.split())
        return None

    def partial(self) -> str:
        text = json.loads(self.rec.PartialResult()).get("partial", "")
        return "".join(text.split())

    def final(self) -> str:
        text = json.loads(self.rec.FinalResult()).get("text", "")
        return "".join(text.split())

    def reset(self):
        self.rec = vosk.KaldiRecognizer(get_model(), SAMPLE_RATE)
