"""逐块打印 barge-in 判定依据，用于校准阈值。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_frontend as T  # noqa: E402
from frontend import AudioFrontend, FRAME  # noqa: E402

fe, near, echo, clean, probs, actives, barges = T.run(True)
sr = T.SR
block = T.BLOCK
user_blocks = []
for b in range(len(probs)):
    a = near[b * block:(b + 1) * block]
    e = echo[b * block:(b + 1) * block]
    sig = a - e
    user_blocks.append(float(np.sqrt(np.mean(sig ** 2) + 1e-12)) > 0.01)
print("idx  prob  act  barge  user  near_rms  clean_rms")
for b in range(28, 76):
    a = near[b * block:(b + 1) * block]
    c = clean[b * block:(b + 1) * block]
    print(f"{b:3d} {probs[b]:.3f} {int(actives[b])}   {int(barges[b])}    {int(user_blocks[b])}   "
          f"{float(np.sqrt(np.mean(a ** 2) + 1e-12)):.4f}    {float(np.sqrt(np.mean(c ** 2) + 1e-12)):.4f}")
