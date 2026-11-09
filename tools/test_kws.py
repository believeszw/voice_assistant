"""验收本地唤醒词（sherpa-onnx KWS）。

正样本：4 个唤醒词 × 3 种语速，SAPI 合成；再叠 SNR 10/5/0 dB 噪声。
负样本：不含唤醒词的指令音频 + 白噪声 + 静音（用于估误唤醒）。
指标：唤醒率、触发位置（相对音频结束，负值=还没播完就触发）、误唤醒次数/小时、实时率。

用法：
    python tools/test_kws.py            # 用 kws.py 默认参数评估
    python tools/test_kws.py --sweep    # 扫 threshold / score，选一组平衡点
"""

import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import kws  # noqa: E402
from test_sherpa import TEXTS  # noqa: E402  用于筛掉含唤醒词的音频

OUT = Path(__file__).resolve().parent / "kwswav"
WAV = Path(__file__).resolve().parent / "wav"
SR = 16000
WAKE_TEXTS = ["小助手", "你好小助手", "小爱小助手", "小助手小助手"]
RATES = [-2, 0, 2]


def synth_rate(text: str, path: Path, rate: int):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.Rate = rate
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(path), 3, False)
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()
    voice.AudioOutputStream = None


def load_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        ch, sr = w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        n = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)
    return x.astype(np.float32)


def to_pcm(x: np.ndarray) -> bytes:
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


def add_noise(x: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    p_sig = float(np.mean(x ** 2)) or 1e-9
    p_noise = p_sig / (10 ** (snr_db / 10))
    y = x + rng.normal(0.0, np.sqrt(p_noise), len(x))
    peak = float(np.abs(y).max()) or 1.0
    return (y * (0.7 / peak)).astype(np.float32)


def detect(det: kws.WakeWord, x: np.ndarray, chunk: int = 1600):
    """按 0.1s 块喂音频，返回 (命中词, 触发位置秒)。"""
    det.reset()
    for off in range(0, len(x), chunk):
        hit = det.feed(to_pcm(x[off:off + chunk]))
        if hit:
            return hit, (off + chunk) / SR
    return None, len(x) / SR


def build_samples():
    OUT.mkdir(exist_ok=True)
    pos = []
    for text in WAKE_TEXTS:
        for rate in RATES:
            p = OUT / f"wake_{text}_{rate}.wav"
            if not p.exists():
                synth_rate(text, p, rate)
            pos.append((text, rate, load_16k(p)))
    neg = []
    for i, text in enumerate(TEXTS):
        if any(w in text for w in WAKE_TEXTS):
            continue  # 本身含唤醒词，不能当负样本
        p = WAV / f"case_{i}.wav"
        if p.exists():
            neg.append((f"case_{i}", load_16k(p)))
    rng = np.random.default_rng(20261108)
    neg.append(("噪声30s", rng.normal(0, 0.01, SR * 30).astype(np.float32)))
    neg.append(("静音30s", np.zeros(SR * 30, dtype=np.float32)))
    return pos, neg


def evaluate(det, pos, neg):
    """返回指标 dict。"""
    result = {}
    for label, snr in (("clean", None), ("SNR10", 10), ("SNR5", 5), ("SNR0", 0)):
        rng = np.random.default_rng(20261108)
        hits, delays = 0, []
        for _text, _rate, x in pos:
            y = x if snr is None else add_noise(x, snr, rng)
            hit, pos_s = detect(det, y)
            if hit:
                hits += 1
                delays.append(pos_s - len(y) / SR)
        result[label] = (hits / len(pos), float(np.mean(delays)) if delays else 0.0)
    false_hits, total_sec = 0, 0.0
    for _name, x in neg:
        total_sec += len(x) / SR
        hit, _ = detect(det, x)
        if hit:
            false_hits += 1
    result["false_per_hour"] = false_hits / (total_sec / 3600) if total_sec else 0.0
    result["false_hits"] = false_hits
    result["neg_minutes"] = total_sec / 60
    return result


def fmt(result):
    lines = []
    for label in ("clean", "SNR10", "SNR5", "SNR0"):
        rate, delay = result[label]
        lines.append(f"  {label:<6}{rate:>7.0%}{delay:>12.2f} s")
    lines.append(f"  误唤醒 {result['false_hits']} 次 / {result['neg_minutes']:.1f} min"
                 f" → {result['false_per_hour']:.1f} 次/小时")
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pos, neg = build_samples()
    print(f"正样本 {len(pos)} 条；负样本 {len(neg)} 条")

    if "--sweep" in sys.argv:
        best = None
        for th in (0.15, 0.25, 0.35, 0.5):
            for score in (0.5, 1.0, 2.0):
                det = kws.WakeWord(threshold=th, score=score)
                if not det.available():
                    print("KWS 不可用:", det.err)
                    return 1
                r = evaluate(det, pos, neg)
                print(f"\nthreshold={th} score={score}\n{fmt(r)}")
                if not best or (r["clean"][0] + r["SNR5"][0] - r["false_per_hour"] * 0.05
                                > best[0]):
                    best = (r["clean"][0] + r["SNR5"][0] - r["false_per_hour"] * 0.05, th, score, r)
        print("\n推荐:", f"threshold={best[1]} score={best[2]}")
        print(fmt(best[3]))
        return 0

    det = kws.WakeWord()
    print("KWS 可用:", det.available(), det.err)
    if not det.available():
        return 1
    r = evaluate(det, pos, neg)
    print("\n=== 唤醒率 / 触发位置（相对音频结束） ===")
    print(fmt(r))
    t0 = time.time()
    x = pos[0][2]
    for off in range(0, len(x), 1600):
        det.feed(to_pcm(x[off:off + 1600]))
    print(f"\n实时率: {(time.time() - t0) / (len(x) / SR) * 100:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
