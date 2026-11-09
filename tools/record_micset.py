"""录一套「外放 -> 麦克风」的真实远场测试集。

做法：SAPI 合成 12 句（复用 tools/wav 里已有的 case_*.wav），从默认扬声器播放，
同时用麦克风采集，存成 tools/micwav/mic_case_*.wav（16k/单声道）。
这样测出来的识别率包含房间混响、扬声器失真、麦克风底噪，比纯合成音频更接近真实场景。
"""

import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
WAV_DIR = Path(__file__).resolve().parent / "wav"
OUT_DIR = Path(__file__).resolve().parent / "micwav"
SR = 16000
REC_SR = 16000


def load_wav(path: Path):
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        width = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    assert width == 2
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != REC_SR:
        n = int(len(data) / sr * REC_SR)
        x_old = np.linspace(0, len(data) / sr, len(data), endpoint=False)
        x_new = np.linspace(0, len(data) / sr, n, endpoint=False)
        data = np.interp(x_new, x_old, data).astype(np.float32)
    return data


def record_play(samples: np.ndarray, extra_tail: float = 0.8):
    """先开麦，再外放，录到播放结束后 extra_tail 秒。"""
    frames = []

    def cb(indata, n, t, status):
        frames.append(bytes(indata))

    duration = len(samples) / REC_SR + extra_tail
    with sd.RawInputStream(samplerate=REC_SR, blocksize=800, dtype="int16", channels=1, callback=cb):
        time.sleep(0.15)
        sd.play(samples, REC_SR, blocking=False)
        time.sleep(duration)
        sd.stop()
    raw = b"".join(frames)
    data = np.frombuffer(raw, dtype=np.int16)
    # 去掉开头 0.15s 预录
    skip = int(0.15 * REC_SR)
    return data[skip:]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(exist_ok=True)
    print("麦克风:", sd.query_devices(sd.default.device[0])["name"])
    print("扬声器:", sd.query_devices(sd.default.device[1])["name"])
    for i in range(12):
        src = WAV_DIR / f"case_{i}.wav"
        if not src.exists():
            print("missing", src)
            continue
        samples = load_wav(src)
        data = record_play(samples)
        out = OUT_DIR / f"mic_case_{i}.wav"
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(REC_SR)
            wf.writeframes(data.tobytes())
        print(f"[{i}] {src.stem} 播放 {len(samples)/REC_SR:.2f}s -> 录制 {len(data)/REC_SR:.2f}s -> {out.name}")
        time.sleep(0.2)
    print("ALL_DONE")


if __name__ == "__main__":
    main()
