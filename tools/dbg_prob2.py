"""临时诊断：逐块打印 clean rms / ratio / prob（不判 barge），用于定阈值。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_barge_ux as U  # noqa: E402
from frontend import AudioFrontend  # noqa: E402

SR, BLOCK = U.SR, U.BLOCK


def dump(name, far, near, t0, t1):
    fe = AudioFrontend()
    fe.reset()
    print(f"== {name}")
    prev = None
    for i in range(0, len(near) - BLOCK, BLOCK):
        fb = far[i:i + BLOCK]
        nb = near[i:i + BLOCK]
        fe.push_far((np.clip(fb, -1, 1) * 32768).astype(np.int16).tobytes())
        fe.process((np.clip(nb, -1, 1) * 32768).astype(np.int16).tobytes())
        t = i / SR
        if not (t0 <= t <= t1):
            continue
        ev = fe.barge_evidence
        m = dict(x.split("=") for x in ev.split() if "=" in x)
        print(f"  t={t:.2f} rms={float(m.get('rms',0)):.3f} "
              f"ratio={float(m.get('ratio',0)):5.1f} prob={float(m.get('prob',0)):.2f} "
              f"pk={float(m.get('pk',0)):.2f}")


far, near = U.scene(0.20, 0.05, seconds=3.0)
dump("leak=0.20 rms=0.05（小声说话）", far, near, 0.9, 1.8)

far, near = U.scene(0.05, 0.0, seconds=3.0)
spike = near.copy()
spike[int(1.0 * SR):int(1.12 * SR)] += 0.30
spike[int(1.3 * SR):int(1.42 * SR)] += 0.30
dump("纯播报+两个 0.30 尖峰（非人声）", far, spike, 0.9, 1.6)
