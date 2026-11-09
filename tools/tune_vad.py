"""调 VAD 阈值/挂起时间：先跑一遍前端收集概率序列，再离线网格搜索。"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frontend  # noqa: E402
from tools.test_frontend import BLOCK, USER_LEN, USER_START, build_scene  # noqa: E402


def collect(gain: float):
    far, near, echo = build_scene()
    fe = frontend.AudioFrontend(aec_enabled=True)
    # 用固定阈值收原始概率：临时把阈值压低不影响 prob 记录
    probs, actives = [], []
    for i in range(0, len(near) - BLOCK, BLOCK):
        fe.push_far((far[i:i + BLOCK] * 32768).astype(np.int16).tobytes()
                    if i < len(far) else b"")
        near_blk = (near[i:i + BLOCK] * 32768 * gain).clip(-32768, 32767).astype(np.int16)
        clean, prob, active = fe.process(near_blk.tobytes())
        probs.append(prob)
        actives.append(active)
    return np.array(probs)


def simulate(probs, threshold, hangar, min_speech, blk=BLOCK):
    """把 32ms 概率序列按 50ms 块映射回 active 序列。"""
    active = np.zeros(len(probs), dtype=bool)
    hold = 0
    run = 0
    for i, p in enumerate(probs):
        if p >= threshold:
            run += 1
            hold = hangar
            if run >= min_speech:
                active[i] = True
        else:
            run = 0
            if hold > 0:
                active[i] = True
                hold -= 1
    return active


def score(probs):
    user0 = int(USER_START / BLOCK)
    user1 = int((USER_START + USER_LEN) / BLOCK)
    best = None
    for threshold in (0.15, 0.2, 0.25, 0.3, 0.35, 0.4):
        for hangar in (5, 8, 10, 12, 16, 20):
            for min_speech in (1, 2, 3):
                blocks = simulate(probs, threshold, hangar, min_speech)
                hit = blocks[user0:user1].mean() if user1 > user0 else 0
                mask = np.ones(len(blocks), bool)
                mask[max(0, user0 - 1):user1 + 1] = False
                fp = blocks[mask].mean()
                first = int(np.argmax(blocks[user0:user1])) if hit > 0 else -1
                lat = first * BLOCK / 16000 if first >= 0 else 99
                if best is None or (hit - fp) > (best[0] - best[1]):
                    best = (hit, fp, lat, threshold, hangar, min_speech)
    return best


def main():
    for gain in (1.0, 2.0, 4.0):
        probs = collect(gain)
        print("gain", gain, "prob mean", round(float(probs.mean()), 3),
              "max", round(float(probs.max()), 3))
        hit, fp, lat, th, hg, ms = score(probs)
        print("  best: hit", round(float(hit), 2), "fp", round(float(fp), 3),
              "lat", round(float(lat), 2), "th", th, "hang", hg, "min", ms)


if __name__ == "__main__":
    main()
