"""声学闭环：扬声器播放唤醒词，麦克风采集，KWS 实时检测。

用于回答「真机上 KWS 能不能被外放声触发」，不依赖 assistant 主程序。
"""
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audio  # noqa: E402
import kws as kws_mod  # noqa: E402


def load_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        ch, width, sr = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch)[:, 0]
    if sr != 16000:
        duration = len(data) / sr
        n = int(duration * 16000)
        data = np.interp(np.linspace(0, duration, n, endpoint=False),
                         np.linspace(0, duration, len(data), endpoint=False), data)
    return np.clip(data, -32768, 32767).astype(np.int16)


def play_bg(data: np.ndarray):
    sd.play(np.clip(data.astype(np.float32) * 6.0, -32768, 32767).astype(np.int16), 16000)


def main():
    wav = ROOT / "tools" / "kwswav" / "wake_你好小助手_0.wav"
    if not wav.exists():
        wav = ROOT / "tools" / "kwswav" / "wake_小助手_0.wav"
    print("播放:", wav.name, "输出设备:", sd.query_devices(kind="output")["name"])
    pcm = load_16k(wav)

    wake = kws_mod.WakeWord(log=print)
    print("KWS available:", wake.available(), wake.err)

    hits = []
    rms_series = []
    with audio.Mic() as mic:
        time.sleep(0.3)
        mic.flush()
        play_bg(pcm)
        t0 = time.time()
        deadline = t0 + len(pcm) / 16000 + 1.5
        while time.time() < deadline:
            block = mic.read(0.2)
            if not block:
                continue
            rms_series.append(audio.rms_of(block))
            hit = wake.feed(block)
            if hit:
                hits.append((round(time.time() - t0, 2), hit))
                print(f"  KWS 命中 @ {hits[-1][0]}s: {hit!r}")
    sd.stop()
    if rms_series:
        a = np.array(rms_series)
        print(f"麦克风 rms: max={a.max():.0f} mean={a.mean():.0f} p90={np.percentile(a,90):.0f} 块数={len(a)}")
    print("命中数:", len(hits))
    print("PASS" if hits else "FAIL（麦克风没听到外放唤醒词或 KWS 未触发）")


if __name__ == "__main__":
    main()
