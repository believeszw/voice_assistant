"""从干净的合成音频造「受控远场集」：房间反射 + 噪声，用来看各引擎在低信噪比下的鲁棒性。

做法（每个 case）：
1) 单次早期反射：把原信号延后 60 ms、衰减 0.3 叠回去（模拟墙面反射）；
2) 加高斯白噪声，按目标 SNR 定噪声电平（默认 SNR=10dB 与 5dB 两套）；
3) 峰值归一到 0.5，存到 tools/farwav_10db / tools/farwav_5db。
"""

import sys
import wave
from pathlib import Path

import numpy as np

SR = 16000
WAV_DIR = Path(__file__).resolve().parent / "wav"


def load(path: Path):
    with wave.open(str(path), "rb") as w:
        ch, width, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    assert width == 2, path
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        n = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x), n, endpoint=False),
                      np.arange(len(x)), x)
    return x.astype(np.float64)


def save(path: Path, x: np.ndarray):
    y = np.clip(x, -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def make(x: np.ndarray, snr_db: float, rng: np.random.Generator):
    # 早期反射
    delay = int(0.060 * SR)
    y = x.copy()
    y[delay:] += 0.3 * x[:-delay]
    # 噪声电平按语音段功率定
    p_sig = float(np.mean(y ** 2))
    p_noise = p_sig / (10 ** (snr_db / 10))
    y = y + rng.normal(0.0, np.sqrt(p_noise), len(y))
    # 峰值归一，模拟设备 AGC
    peak = float(np.abs(y).max()) or 1.0
    return y * (0.5 / peak)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rng = np.random.default_rng(20261108)
    for snr in (10, 5, 0):
        out = Path(__file__).resolve().parent / f"farwav_{snr}db"
        out.mkdir(exist_ok=True)
        for src in sorted(WAV_DIR.glob("case_*.wav")):
            x = load(src)
            save(out / src.name, make(x, snr, rng))
        print(f"[done] {out} 12 files, SNR={snr}dB")


if __name__ == "__main__":
    main()
