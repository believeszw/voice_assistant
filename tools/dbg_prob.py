"""临时诊断：打断判定里 prob 与 rms 的时序，用于定阈值。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_barge_ux as U  # noqa: E402
from frontend import AudioFrontend  # noqa: E402

SR, BLOCK = U.SR, U.BLOCK


def dump(name, far, near, start=0.6):
    fe = AudioFrontend()
    fe.reset()
    rows = []
    for i in range(0, len(near) - BLOCK, BLOCK):
        fb = far[i:i + BLOCK]
        nb = near[i:i + BLOCK]
        fe.push_far((np.clip(fb, -1, 1) * 32768).astype(np.int16).tobytes())
        fe.process((np.clip(nb, -1, 1) * 32768).astype(np.int16).tobytes())
        t = i / SR
        if t >= start and fe.barge_in:
            rows.append((round(t, 2), fe.barge_evidence))
            if len(rows) >= 6:
                break
    print(f"== {name}")
    for t, ev in rows:
        print(f"  t={t} {ev}")


for leak, rms in ((0.05, 0.12), (0.20, 0.12), (0.20, 0.05)):
    far, near = U.scene(leak, rms, seconds=4.0)
    dump(f"leak={leak} rms={rms}", far, near)
