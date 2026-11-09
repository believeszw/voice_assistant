"""Offline acceptance test for the AEC3 wrapper class (voice_assistant/aec3.py).

Scene matches tools/test_frontend.py: far = case_1 + 0.4s silence + case_6,
echo = far delayed 80ms * 0.35 + white noise, user speech from 1.6s.
Reports ERLE in steady state (skip first 0.6s of convergence).
"""
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from aec3 import AEC3

SR = 16000
FRAME = 160          # AEC3 10 ms
BLOCK = 800          # 50 ms metric blocks
USER_START = 1.6
USER_LEN = 2.0
DELAY = 0.080


def read_wav(path, rate=SR):
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        raw = w.readframes(w.getnframes())
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        src_rate = w.getframerate()
    if src_rate != rate:
        n = int(round(len(data) * rate / src_rate))
        data = np.interp(np.linspace(0, len(data), n, endpoint=False),
                         np.arange(len(data)), data).astype(np.float32)
    return data


def build_scene():
    a = read_wav(os.path.join(HERE, "wav", "case_1.wav"))
    b = read_wav(os.path.join(HERE, "wav", "case_6.wav"))
    far = np.concatenate([a, np.zeros(int(0.4 * SR), np.float32), b])
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 0.0015, len(far)).astype(np.float32)
    d = int(DELAY * SR)
    echo = np.concatenate([np.zeros(d, np.float32), far[: len(far) - d] * 0.35]) + noise
    user = read_wav(os.path.join(HERE, "wav", "case_5.wav"))[: int(USER_LEN * SR)]
    near = echo.copy()
    start = int(USER_START * SR)
    near[start:start + len(user)] += user
    return far, echo, near


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2) + 1e-12))


def main():
    aec = AEC3()
    aec._lib.wap_set_stream_delay(aec._h, int(DELAY * 1000))
    far, echo, near = build_scene()
    n = (len(near) // FRAME) * FRAME
    far = np.pad(far, (0, max(0, n - len(far))))[:n]
    near, echo = near[:n], echo[:n]

    out = np.zeros(n, dtype=np.float32)
    for i in range(0, n, FRAME):
        y, _ = aec.process(near[i:i + FRAME], far[i:i + FRAME])
        out[i:i + FRAME] = y
    aec.close()

    skip = int(0.6 * SR)
    b = BLOCK
    erles = []
    for s in range(0, n - b, b):
        if s < skip:
            continue
        ne, ce = rms(echo[s:s + b]), rms(out[s:s + b])
        if ne > 1e-4:
            erles.append(10 * np.log10((ne ** 2 + 1e-12) / (ce ** 2 + 1e-12)))
    erle = float(np.mean(erles)) if erles else -99.0
    print(f"aec3 class ERLE={erle:.3f} dB  blocks={len(erles)}", flush=True)
    print("PASS" if erle >= 6 else "FAIL", flush=True)


if __name__ == "__main__":
    main()
