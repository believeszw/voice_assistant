"""AEC + VAD 前端验收：用合成回声场景量化指标。

场景：
- far（参考/播放）用 tools/wav 里两条 TTS 语音拼成约 4 s；
- 喇叭到麦克风的回声 = far 延迟 80 ms、衰减 0.35、加房间噪声；
- 1.6 s 起叠加一段"用户说话"（另一条 TTS），持续约 2 s，构成双讲；
- 50 ms 一块喂 frontend，统计：
  1) 纯回声段 ERLE（回声抑制量）；
  2) 双讲段用户语音被 VAD 检出的比例（打断能力）；
  3) 纯回声段 VAD 误触发比例（播报中误打断）；
  4) 打断延迟：用户开口 → 首次 VAD 判定 active 的时间。
对照组：aec_enabled=False（只看 VAD 原始表现）。

用法：python tools/test_frontend.py
"""

import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frontend  # noqa: E402

WAV_DIR = ROOT / "tools" / "wav"
SR = 16000
DELAY = int(0.080 * SR)
ECHO_GAIN = 0.35
USER_GAIN = 3.0      # 双讲时用户近场语音相对回采回声的电平（离线场景原来偏小，按近场实测放大）
BLOCK = 800          # 50 ms
USER_START = int(1.6 * SR)
USER_LEN = int(2.0 * SR)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        data = w.readframes(w.getnframes())
    x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    if sr != SR:
        n = int(round(len(x) * SR / sr))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def pick(name: str) -> np.ndarray:
    p = WAV_DIR / name
    if not p.exists():
        raise SystemExit(f"缺少测试音频 {p}")
    return read_wav(p)


def build_scene():
    far1 = pick("case_1.wav")     # 小助手，打开记事本
    far2 = pick("case_6.wav")     # 另一条指令
    far = np.concatenate([far1, np.zeros(int(0.4 * SR), np.float32), far2])
    user = pick("case_5.wav")
    user = np.resize(user, USER_LEN)

    echo = np.zeros(len(far) + DELAY, dtype=np.float32)
    echo[DELAY:DELAY + len(far)] = far * ECHO_GAIN
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 0.0015, len(echo)).astype(np.float32)
    near = echo + noise
    near[USER_START:USER_START + len(user)] += user * USER_GAIN
    return far, near, echo


def run(aec_enabled: bool):
    far, near, echo = build_scene()
    fe = frontend.AudioFrontend(aec_enabled=aec_enabled)
    probs, actives, barges, cleans = [], [], [], []
    for i in range(0, len(near) - BLOCK, BLOCK):
        blk = near[i:i + BLOCK]
        fe.push_far((far[i:i + BLOCK] * 32768).astype(np.int16).tobytes()
                    if i < len(far) else b"")
        clean, prob, active = fe.process((blk * 32768).astype(np.int16).tobytes())
        cleans.append(np.frombuffer(clean, dtype=np.int16).astype(np.float32) / 32768.0)
        probs.append(prob)
        actives.append(active)
        barges.append(fe.barge_in)
    clean = np.concatenate(cleans) if cleans else np.zeros(0, np.float32)
    return fe, near, echo, clean, np.array(probs), np.array(actives), np.array(barges)


def metrics(aec_enabled: bool):
    fe, near, echo, clean, probs, actives, barges = run(aec_enabled)
    raw = barges if aec_enabled else actives
    # 打断一旦触发就会停播报、进入下一轮；此后的块按「已检出」计，
    # 否则同一段用户语音会被反复计为漏检。
    detect = np.maximum.accumulate(raw)
    n = min(len(clean), len(near))
    clean, near_t, echo_t = clean[:n], near[:n], echo[:n]

    # 纯回声段：0 ~ USER_START 和 用户语音结束后；ERLE 只看稳态（跳过 AEC 收敛的 0.6s）
    user_end = USER_START + USER_LEN
    warm = int(0.6 * SR)
    echo_mask = np.zeros(n, dtype=bool)
    echo_mask[warm:USER_START - 800] = True
    if user_end + 800 < n:
        echo_mask[user_end + 800:] = True
    erle = 10 * np.log10((np.mean(echo_t[echo_mask] ** 2) + 1e-12) /
                         (np.mean(clean[echo_mask] ** 2) + 1e-12))

    # VAD 统计（按 50ms 块）：只统计「用户真的在说话」的块（按 near-echo 能量判定）
    nblk = len(probs)
    user_blk0 = USER_START // BLOCK
    user_blk1 = min(nblk, user_end // BLOCK)
    echo_blocks = [b for b in range(nblk) if (b < user_blk0 - 1 or b > user_blk1)]
    user_sig = near_t - echo_t
    user_blocks = [b for b in range(user_blk0, user_blk1)
                   if b * BLOCK < n and float(np.sqrt(np.mean(
                       user_sig[b * BLOCK:(b + 1) * BLOCK] ** 2))) > 0.01]
    if not user_blocks:
        user_blocks = list(range(user_blk0, user_blk1))
    hit = np.mean([detect[b] for b in user_blocks]) if user_blocks else 0.0
    fp = np.mean([raw[b] for b in echo_blocks]) if echo_blocks else 0.0
    first = next((b for b in user_blocks if raw[b]), None)
    latency = (first - user_blk0) * BLOCK / SR if first is not None else float("nan")
    return dict(erle=erle, hit=hit, fp=fp, latency=latency,
                prog=float(np.mean(probs[user_blocks])) if user_blocks else 0.0,
                eprog=float(np.mean(probs[echo_blocks])) if echo_blocks else 0.0,
                fe=fe)


def main():
    print("=== AEC 开 ===")
    on = metrics(True)
    for k in ("erle", "hit", "fp", "latency", "prog", "eprog"):
        print(f"{k:8s}: {on[k]:.3f}")
    print("=== AEC 关（对照）===")
    off = metrics(False)
    for k in ("erle", "hit", "fp", "latency", "prog", "eprog"):
        print(f"{k:8s}: {off[k]:.3f}")

    ok = True
    if on["erle"] < 6.0:
        print(f"[FAIL] ERLE {on['erle']:.1f} dB < 6 dB")
        ok = False
    if on["hit"] < 0.8:
        print(f"[FAIL] 双讲用户语音检出率 {on['hit']:.2f} < 0.8")
        ok = False
    if on["fp"] > 0.2:
        print(f"[FAIL] 纯回声段误触发 {on['fp']:.2f} > 0.2")
        ok = False
    if not np.isnan(on["latency"]) and on["latency"] > 0.6:
        print(f"[FAIL] 打断延迟 {on['latency']:.2f}s > 0.6s")
        ok = False
    print("PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
