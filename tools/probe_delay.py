"""探测真实设备链路的播放->麦克风延迟。"""
import io
import sys
import threading
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402

try:
    import sounddevice as sd
except Exception as exc:
    print("sounddevice 不可用:", exc)
    sys.exit(1)

SR = 16000
FRAME = 256


def _read_wav(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        ch, rate = wf.getnchannels(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def _resample(x, src, dst=SR):
    if src == dst:
        return x
    n = int(len(x) * dst / src)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def main():
    wav = llm.tts_wav("一 二 三 四 五 六 七 八 九 十，测试延迟。")
    x, rate = _read_wav(wav)
    x16 = _resample(x, rate)
    far = np.zeros(SR * 6, dtype=np.float32)
    far[:len(x16)] = x16
    print(f"播报 {len(x16)/SR:.1f}s")

    def play():
        with sd.OutputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
            pos = 0
            while pos < len(far):
                seg = far[pos:pos + FRAME]
                st.write(np.clip(seg * 32768.0, -32768, 32767).astype(np.int16))
                pos += FRAME

    threading.Thread(target=play, daemon=True).start()

    near = np.zeros(SR * 6, dtype=np.float32)
    pos = 0
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
        while pos < len(near):
            data, _ = st.read(FRAME)
            near[pos:pos + FRAME] = data[:, 0] / 32768.0
            pos += FRAME

    # 全段互相关，找 near 相对 far 的滞后
    n = len(near)
    spec = np.fft.rfft(near) * np.conj(np.fft.rfft(far))
    cc = np.fft.irfft(spec, n)
    lags = np.arange(n)
    lags[lags > n // 2] -= n
    order = np.argsort(cc)[::-1]
    best = [(int(lags[i]), float(cc[i])) for i in order[:6]]
    print("互相关峰值 (lag 样本, 值):", best)
    print("near rms=%.4f far rms=%.4f" % (
        float(np.sqrt(np.mean(near ** 2))), float(np.sqrt(np.mean(far ** 2)))))
    for lag, _ in best[:3]:
        if 0 <= lag < SR:
            print(f"  lag={lag} = {lag/SR*1000:.0f} ms")


if __name__ == "__main__":
    main()
