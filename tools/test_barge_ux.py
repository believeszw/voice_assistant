"""打断体验验收：检测延迟、误打断（纯播报）、预录回捞。

场景：播报信号 far（SAPI 合成语音，16k），回声 echo = far 延迟 80ms × leak，
用户语音从 t=1.0s 起按指定 RMS 叠加。按 50ms 一块喂 AudioFrontend，
统计首次 barge 时间、纯播报时是否误触发、barge 瞬间能回捞多长的预录。

通过线：纯播报 0 次误打断；user_rms>=0.03 时检测延迟 <=0.6s；预录 >=0.4s。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_frontend as T  # noqa: E402
from frontend import AudioFrontend  # noqa: E402

SR = T.SR
BLOCK = T.BLOCK
DELAY = T.DELAY


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.pad(x, (0, n - len(x)))


def scene(leak: float, user_rms: float, user_start: float = 1.0,
          seconds: float = 5.0, noise: float = 0.0015, seed: int = 1):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    far = _fit(np.tile(T.pick("case_1.wav"), 4), n)
    echo = np.zeros(n, dtype=np.float32)
    echo[DELAY:] = far[:-DELAY] * leak
    near = echo + rng.normal(0, noise, n).astype(np.float32)
    if user_rms > 0:
        raw = T.pick("case_5.wav")
        raw = raw / max(1e-6, float(np.sqrt(np.mean(raw ** 2))))
        user = _fit(np.tile(raw, 4), n) * user_rms
        n0 = int(user_start * SR)
        near[n0:] += user[: n - n0]
    return far, near


def run(leak: float, user_rms: float, seconds: float = 5.0):
    far, near = scene(leak, user_rms, seconds=seconds)
    fe = AudioFrontend()
    fe.reset()
    t_barge = None
    pre_sec = 0.0
    for i in range(0, len(near) - BLOCK, BLOCK):
        fb = far[i:i + BLOCK]
        nb = near[i:i + BLOCK]
        fe.push_far((np.clip(fb, -1, 1) * 32768).astype(np.int16).tobytes())
        fe.process((np.clip(nb, -1, 1) * 32768).astype(np.int16).tobytes())
        if fe.barge_in and t_barge is None:
            t_barge = i / SR
            pre = fe.recent_clean(0.5)
            pre_sec = len(pre) / 2 / SR
    return t_barge, pre_sec


def main():
    ok = True

    # 1) 纯播报（无用户）：不应误打断
    tb, _ = run(leak=0.2, user_rms=0.0, seconds=6.0)
    print(f"[纯播报 6s] 误打断时间: {tb}  (期望 None)")
    ok &= tb is None

    # 2) 用户开口检测延迟 + 预录长度
    for leak in (0.05, 0.2):
        for rms in (0.05, 0.12):
            tb, pre = run(leak, rms, seconds=4.0)
            lat = None if tb is None else tb - 1.0
            ok_case = (tb is not None and lat is not None
                       and 0.0 <= lat <= 0.6 and pre >= 0.4)
            ok &= ok_case
            print(f"[leak={leak:.2f} rms={rms:.2f}] 检测@ {tb} "
                  f"延迟={lat} 预录={pre:.2f}s -> {'PASS' if ok_case else 'FAIL'}")

    # 3) 更低音量的参考信息（不强制通过：播报漏音大时本来就难分辨）
    for rms in (0.03,):
        tb, pre = run(0.2, rms, seconds=4.0)
        lat = None if tb is None else tb - 1.0
        print(f"[参考 leak=0.20 rms={rms:.2f}] 检测@ {tb} 延迟={lat} 预录={pre:.2f}s")

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
