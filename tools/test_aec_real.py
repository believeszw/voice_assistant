"""真实声学：只播放助手播报，观察 AEC 是否在真实设备链路上收敛。"""
import io
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm
from frontend import AudioFrontend, FRAME

try:
    import sounddevice as sd
except Exception as exc:
    print("sounddevice 不可用:", exc)
    sys.exit(1)

SR = 16000


def _read_wav(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        ch = wf.getnchannels()
        rate = wf.getframerate()
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
    print("合成 TTS ...")
    wav = llm.tts_wav("这是一段比较长的测试播报，用来观察真实设备上的回声抑制效果，请忽略内容。")
    x, rate = _read_wav(wav)
    x16 = _resample(x, rate)
    print(f"播报 {len(x16)/SR:.1f}s @16k")

    stop = threading.Event()
    fe = AudioFrontend()

    def play():
        with sd.OutputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
            pos = 0
            while pos < len(x16) and not stop.is_set():
                seg = x16[pos:pos + FRAME]
                buf = np.zeros(FRAME, dtype=np.float32)
                buf[:len(seg)] = seg
                pcm = np.clip(buf * 32768.0, -32768, 32767).astype(np.int16)
                # far 参考与「写入播放设备的时间线」对齐（生产里 tts.py 也是这样喂的）
                fe.push_far(pcm.tobytes())
                st.write(pcm)
                pos += FRAME

    threading.Thread(target=play, daemon=True).start()

    got = 0
    t0 = time.time()
    next_report = 0.2
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
        while got < SR * 6:
            data, _ = st.read(FRAME)
            near_rms = float(np.sqrt(np.mean((data[:, 0] / 32768.0) ** 2) + 1e-12))
            clean, prob, active = fe.process(data.tobytes())
            got += FRAME
            el = got / SR
            if el >= next_report:
                clean_rms = float(np.sqrt(np.mean((np.frombuffer(clean, np.int16) / 32768.0) ** 2) + 1e-12))
                print(f"t={el:4.1f}s near={near_rms:.4f} clean={clean_rms:.4f} erle={fe.last_erle:6.1f}dB "
                      f"delay={fe.aec.delay if fe.aec else -1} dtd={int(fe.last_dtd)} prob={prob:.2f}")
                next_report += 0.2
    stop.set()
    print("done")


if __name__ == "__main__":
    main()
