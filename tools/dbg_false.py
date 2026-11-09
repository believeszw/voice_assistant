"""调试：真实播报期间 near 能量分布 + 每次 barge 的证据。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio  # noqa: E402
import llm  # noqa: E402
from frontend import AudioFrontend  # noqa: E402
from tts import Speaker  # noqa: E402


def main():
    text = ("这是一段比较长的播报，用来验证播报期间会不会被自己的声音误打断，"
            "同时也检查一下播报会不会中途停。")
    wav = llm.tts_wav(text)
    fe = AudioFrontend()
    fe.reset()
    spk = Speaker()
    spk.far_sink = fe.push_far
    mic = audio.Mic()
    mic.start()
    rms_hist = []
    barges = []
    done = spk.say_async(text)
    try:
        while not done.is_set():
            block = mic.read(0.05)
            if not block:
                continue
            fe.process(block)
            rms_hist.append(fe.last_prob)
            if fe.barge_in:
                barges.append((round(time.time(), 2), fe.barge_evidence))
    finally:
        mic.stop()
        spk.shutdown()
    print("barge 次数:", len(barges))
    for t, ev in barges[:10]:
        print(" ", t, ev)
    # near 能量统计（从 clean_hist 拿不到 rms 时用 evidence 里的值）
    print("prob 均值:", round(sum(rms_hist) / max(1, len(rms_hist)), 3))


if __name__ == "__main__":
    main()
