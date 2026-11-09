"""检查：把 TTS 语音放大后从扬声器播放，麦克风能不能识出来。"""

import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audio  # noqa: E402
import asr  # noqa: E402

WAV_DIR = Path(__file__).resolve().parent / "wav"
WAKE = WAV_DIR / "e2e_wake.wav"
OUT_RATE = 48000


def load(path: Path, peak: int = 30000):
    with wave.open(str(path), "rb") as wf:
        ch, sr = wf.getnchannels(), wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    if ch > 1:
        data = data.reshape(-1, ch)[:, 0]
    data = data.astype(np.float32)
    maxv = float(np.abs(data).max()) or 1.0
    data = data / maxv * peak
    if sr != OUT_RATE:
        duration = len(data) / sr
        n = int(duration * OUT_RATE)
        data = np.interp(np.linspace(0, duration, n, endpoint=False),
                         np.linspace(0, duration, len(data), endpoint=False), data)
    return np.clip(data, -32768, 32767).astype(np.int16)


def main():
    chunks = []

    def record():
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16") as st:
            start = time.time()
            while time.time() - start < 6:
                data, _ = st.read(800)
                chunks.append(bytes(data))

    def play():
        time.sleep(1.0)
        for _ in range(2):
            d = load(WAKE)
            sd.play(d, OUT_RATE)
            sd.wait()
            time.sleep(1.0)

    t1 = threading.Thread(target=record)
    t2 = threading.Thread(target=play)
    t1.start(); t2.start(); t1.join(); t2.join()

    pcm = b"".join(chunks)
    arr = np.frombuffer(pcm, dtype=np.int16)
    print(f"rms={audio.rms_of(pcm):.0f} peak={int(np.abs(arr).max())}")
    print("直接识别:", repr(asr.transcribe_pcm(pcm)))
    for gain in (2, 4):
        boosted = np.clip(arr.astype(np.int32) * gain, -32768, 32767).astype(np.int16).tobytes()
        print(f"gain={gain}:", repr(asr.transcribe_pcm(boosted)))


if __name__ == "__main__":
    main()
