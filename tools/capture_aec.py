"""真实设备抓一段近端麦克风信号和播放源（far），离线找真实延迟与回声增益。"""
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
    played = []

    def play():
        with sd.OutputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
            pos = 0
            while pos < len(x16) and not stop.is_set():
                seg = x16[pos:pos + FRAME]
                buf = np.zeros(FRAME, dtype=np.float32)
                buf[:len(seg)] = seg
                st.write(np.clip(buf * 32768.0, -32768, 32767).astype(np.int16))
                pos += FRAME

    threading.Thread(target=play, daemon=True).start()

    near_parts = []
    got = 0
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
        while got < SR * 6:
            data, _ = st.read(FRAME)
            near_parts.append(data[:, 0].astype(np.float32) / 32768.0)
            got += FRAME
    stop.set()
    near = np.concatenate(near_parts)
    np.savez("tools/aec_capture.npz", near=near, far=x16)
    print("saved near", near.shape, "far", x16.shape,
          "near_rms", float(np.sqrt(np.mean(near ** 2))),
          "far_rms", float(np.sqrt(np.mean(x16 ** 2))))
    print("done")


if __name__ == "__main__":
    main()
