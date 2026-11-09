"""找「麦克风能听到」的输出设备：逐设备播 TTS，算 mic 与源信号的归一化互相关峰值。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm import tts_wav
from tools.test_aec_real import _read_wav, _resample, SR
import sounddevice as sd

FRAME = 256
CANDIDATES = [3, 15, 2, 6, 16, 8]


def measure(dev):
    wav = tts_wav("测试声音，一二三四五。")
    x, rate = _read_wav(wav)
    x16 = _resample(x, rate)
    n = int(SR * 1.2)
    src = x16[:n]
    rec = []
    stop = [False]

    def play():
        try:
            with sd.OutputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME,
                                 device=dev) as st:
                pos = 0
                while pos < len(src) and not stop[0]:
                    seg = src[pos:pos + FRAME]
                    buf = np.zeros(FRAME, dtype=np.float32)
                    buf[:len(seg)] = seg
                    st.write(np.clip(buf * 32768.0, -32768, 32767).astype(np.int16))
                    pos += FRAME
        except Exception as exc:  # noqa: BLE001
            return exc

    import threading
    err = []
    th = threading.Thread(target=play)
    try:
        with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
            th.start()
            got = 0
            while got < len(src) + SR // 2:
                data, _ = st.read(FRAME)
                rec.append(data[:, 0].astype(np.float32) / 32768.0)
                got += FRAME
    finally:
        stop[0] = True
        th.join(timeout=2)
    near = np.concatenate(rec)
    N = len(near) + len(src)
    a = np.fft.rfft(near, N)
    b = np.fft.rfft(src, N)
    cc = np.fft.irfft(a * np.conj(b) / (np.abs(a * np.conj(b)) + 1e-9), N)
    peak = float(np.max(cc[: N // 2]))
    lag = int(np.argmax(cc[: N // 2]))
    rms = float(np.sqrt(np.mean(near ** 2)))
    return peak, lag, rms


def main():
    lines = []
    for dev in CANDIDATES:
        try:
            res = measure(dev)
            if isinstance(res, Exception):
                lines.append(f"dev {dev}: ERR {res}")
            else:
                peak, lag, rms = res
                lines.append(f"dev {dev}: peak {peak:.3f} lag {lag} ({lag / 16:.1f} ms) near_rms {rms:.4f}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"dev {dev}: EXC {exc}")
    Path("tools/device_probe.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
