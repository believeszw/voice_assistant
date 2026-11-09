"""验证：把 far 参考取自「实际写入播放设备的时间线」，看 near 与 far 的真实延迟。"""
import sys
import threading
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm import tts_wav
from tools.test_aec_real import _read_wav, _resample, SR
import sounddevice as sd

FRAME = 256


def main():
    print("合成 TTS ...")
    wav = tts_wav("这是一段比较长的测试播报，用来观察真实设备上的回声抑制效果，请忽略内容。")
    x, rate = _read_wav(wav)
    x16 = _resample(x, rate)
    print(f"播报 {len(x16)/SR:.1f}s")

    stop = threading.Event()
    far_blocks = []

    def play():
        with sd.OutputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
            pos = 0
            while pos < len(x16) and not stop.is_set():
                seg = x16[pos:pos + FRAME]
                buf = np.zeros(FRAME, dtype=np.float32)
                buf[:len(seg)] = seg
                st.write(np.clip(buf * 32768.0, -32768, 32767).astype(np.int16))
                far_blocks.append(buf.copy())
                pos += FRAME

    near_parts = []
    got = 0
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
        threading.Thread(target=play, daemon=True).start()
        while got < SR * 6:
            data, _ = st.read(FRAME)
            near_parts.append(data[:, 0].astype(np.float32) / 32768.0)
            got += FRAME
    stop.set()
    near = np.concatenate(near_parts)
    far = np.concatenate(far_blocks) if far_blocks else np.zeros(1, np.float32)
    np.savez("tools/aec_capture.npz", near=near, far=far)

    # 离线分析：真实延迟 + 最小二乘增益 + ERLE
    N = len(near) + len(far)
    nf = np.fft.rfft(near, N)
    ff = np.fft.rfft(far, N)
    spec = nf * np.conj(ff)
    cc = np.fft.irfft(spec / (np.abs(spec) + 1e-9), N)
    order = np.argsort(cc[:N // 2])[::-1][:5]
    lag = int(order[0])
    n = min(len(near), max(0, len(far) - lag))
    gain = erle = 0.0
    if n > 0:
        ref = far[lag:lag + n]
        gain = float(np.dot(near[:n], ref) / (np.dot(ref, ref) + 1e-12))
        e = near[:n] - gain * ref
        erle = float(10 * np.log10(np.mean(near[:n] ** 2) / (np.mean(e ** 2) + 1e-12)))

    lines = [
        f"near {near.shape} far {far.shape}",
        f"near_rms {float(np.sqrt(np.mean(near ** 2))):.5f} far_rms {float(np.sqrt(np.mean(far ** 2))):.5f}",
        "top_lags " + str([(int(i), round(float(cc[i]), 4)) for i in order]),
        f"lag {lag} ({lag / 16:.1f} ms) gain {gain:.3f} erle {erle:.1f} dB",
        "done",
    ]
    Path("tools/aec_capture_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))



if __name__ == "__main__":
    main()
