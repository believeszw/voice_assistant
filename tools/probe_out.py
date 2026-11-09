"""逐设备探测「外放 -> 麦克风」的回放强度，用来选定远场测试的播放设备。"""

import sys
import time

import numpy as np
import sounddevice as sd

SR = 16000


def record(seconds=1.2):
    frames = []

    def cb(indata, n, t, status):
        frames.append(bytes(indata))

    with sd.RawInputStream(samplerate=SR, blocksize=800, dtype="int16", channels=1, callback=cb):
        time.sleep(seconds)
    data = np.frombuffer(b"".join(frames), dtype=np.int16)
    return data


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tone = 0.6 * np.sin(2 * np.pi * 1000 * np.arange(int(0.8 * SR)) / SR).astype(np.float32)
    for dev in (3, 15, 10, 7, 8, 16):
        try:
            info = sd.query_devices(dev)
            if info["max_output_channels"] < 1:
                continue
            before = record(0.6)
            sd.play(tone, SR, device=dev)
            during = record(1.2)
            sd.stop()
            rms0 = float(np.sqrt((before.astype(np.float64) ** 2).mean()))
            rms1 = float(np.sqrt((during.astype(np.float64) ** 2).mean()))
            peak = int(np.abs(during).max())
            print(f"dev {dev:>2} {info['name'][:34]:34s} before={rms0:6.0f} during={rms1:7.0f} peak={peak:6d}")
        except Exception as exc:  # noqa: BLE001
            print(f"dev {dev:>2} FAIL {exc}")


if __name__ == "__main__":
    main()
