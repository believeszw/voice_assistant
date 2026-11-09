"""探测：播放测试音时，麦克风能否听到——确定本机真正“出声”的输出设备。

对每个候选输出设备播放 0.8 s 440 Hz 音（48k 单声道），同时采集麦克风，
打印麦克风 rms/peak。rms 明显高于底噪的那个设备就是实际可听设备。
"""
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import audio  # noqa: E402


def tone(seconds=0.8, freq=440.0, rate=48000, amp=0.9):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)


def measure(device, rate=48000):
    data = tone(rate=rate)
    peak = rms = 0.0
    with audio.Mic() as mic:
        time.sleep(0.25)
        mic.flush()
        sd.play(data, rate, device=device)
        t0 = time.time()
        vals = []
        while time.time() - t0 < len(data) / rate + 0.35:
            block = mic.read(0.1)
            if block:
                vals.append(audio.rms_of(block))
        sd.stop()
        if vals:
            arr = np.array(vals)
            peak, rms = float(arr.max()), float(arr.mean())
    return peak, rms


def main():
    print("默认设备:", sd.default.device)
    print()
    candidates = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            candidates.append((i, d["name"], int(d["default_samplerate"])))
    # 只测常见的前几个 + 显式设备
    pick = []
    for i, name, sr in candidates:
        if any(k in name for k in ("E3500", "Realtek", "Speakers", "扬声器", "耳机", "Headphones")):
            pick.append((i, name, sr))
    if not pick:
        pick = candidates[:5]
    for i, name, sr in pick[:6]:
        for rate in (48000, 44100):
            try:
                peak, rms = measure(i, rate)
            except Exception as e:  # noqa: BLE001
                print(f"[{i}] {name} @{rate}: 播放失败 {type(e).__name__}: {e}")
                continue
            print(f"[{i}] {name} @{rate}: 麦克风 rms mean={rms:.0f} peak={peak:.0f}")
    print()
    print("如果全部 rms < 200，说明本机没有可听的外放（或麦克风离得太远）。")


if __name__ == "__main__":
    main()
