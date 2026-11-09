"""验收：音频前端的降噪（谱减）与自动增益（AGC）。

三组数据：
1. AGC 电平拉齐：把干净语音缩放到不同电平，看输出 RMS 是否拉回目标、峰值不削波；
2. NS 降噪：干净语音叠加白噪声（SNR 10/5/0 dB），对比降噪前后 SenseVoice 的 CER；
3. NS 对唤醒的收益：带噪唤醒词，对比降噪前后 KWS 命中率。

用法：python tools/test_ns_agc.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import frontend  # noqa: E402
import kws as kws_mod  # noqa: E402
from test_sherpa import TEXTS, cer, load_wav, make_sensevoice, run_offline  # noqa: E402

SR = 16000
WAV = Path(__file__).resolve().parent / "wav"
KWSWAV = Path(__file__).resolve().parent / "kwswav"
RNG = np.random.default_rng(20261108)


def to_pcm(x: np.ndarray) -> bytes:
    return np.clip(x * 32767.0, -32768, 32767).astype(np.int16).tobytes()


def rms_db(x: np.ndarray) -> float:
    return 20.0 * np.log10(max(1e-9, float(np.sqrt(np.mean(x ** 2)))))


def add_white(x: np.ndarray, snr_db: float) -> np.ndarray:
    n = RNG.standard_normal(len(x)).astype(np.float32)
    n *= np.sqrt(np.mean(x ** 2) / (np.mean(n ** 2) * 10.0 ** (snr_db / 10.0)))
    return (x + n).astype(np.float32)


def test_agc() -> bool:
    print("== 1. AGC 电平拉齐 ==")
    target = 0.05
    clean = load_wav(WAV / "case_1.wav")
    peak0 = float(np.max(np.abs(clean))) or 1.0
    ok = True
    for level_peak in (0.02, 0.08, 0.3):
        x = (clean / peak0 * level_peak).astype(np.float32)
        agc = frontend.AGC(target_rms=target)
        out = np.zeros_like(x)
        for i in range(0, len(x), 512):
            out[i:i + 512] = agc.process(x[i:i + 512])
        in_db, out_db = rms_db(x), rms_db(out)
        peak = float(np.max(np.abs(out)))
        err = abs(out_db - 20 * np.log10(target))
        good = peak <= 0.99 and err <= 8.0
        ok = ok and good
        print(f"  输入峰值 {level_peak:.2f}：输入 {in_db:6.1f} dBFS → "
              f"输出 {out_db:6.1f} dBFS，峰值 {peak:.2f}  {'OK' if good else 'FAIL'}")
    print(f"  AGC: {'PASS' if ok else 'FAIL'}")
    return ok


def test_ns_cer() -> bool:
    print("\n== 2. 降噪前后 SenseVoice CER（干净语音 + 白噪声）==")
    rec = make_sensevoice()
    cases = list(range(2, 8))  # 打开记事本 / 现在几点了 / 把音量调大一点 / 下一首 / 截个屏 / 关闭计算器
    rows = []
    ok = True
    for snr_db in (10.0, 5.0, 0.0):
        cers_raw, cers_enh = [], []
        for idx in cases:
            x = load_wav(WAV / f"case_{idx}.wav")
            noisy = add_white(x, snr_db)
            enh = np.frombuffer(frontend.enhance_pcm(to_pcm(noisy)),
                                dtype=np.int16).astype(np.float32) / 32768.0
            hyp_raw, _ = run_offline(rec, noisy)
            hyp_enh, _ = run_offline(rec, enh)
            ref = TEXTS[idx]
            cers_raw.append(cer(ref, hyp_raw))
            cers_enh.append(cer(ref, hyp_enh))
        raw, enh = float(np.mean(cers_raw)), float(np.mean(cers_enh))
        better = enh <= raw + 1e-6
        ok = ok and better
        rows.append((snr_db, raw, enh))
        print(f"  SNR {snr_db:4.0f} dB：原始 CER {raw:.3f} → 降噪后 {enh:.3f}  "
              f"{'↓' if enh < raw else ('=' if enh == raw else '↑（变差）')}")
    print(f"  NS(识别): {'PASS' if ok else 'FAIL'}")
    return ok


def test_ns_kws() -> bool:
    print("\n== 3. 降噪前后 KWS 唤醒命中（带噪唤醒词）==")
    det = kws_mod.WakeWord()
    if not det.available():
        print("  KWS 不可用，跳过")
        return True
    files = sorted(KWSWAV.glob("wake_*_0.wav"))
    if not files:
        print("  缺少唤醒音频（tools/kwswav/wake_*_0.wav），跳过")
        return True
    ok = True
    for snr_db in (5.0, 0.0):
        hit_raw = hit_enh = 0
        for f in files:
            x = load_wav(f)
            noisy = add_white(x, snr_db)
            # 唤醒链路只过 NS（不做 AGC），用与 AudioFrontend 相同的语音保护档
            ns = frontend.NoiseSuppressor(speech_floor=0.35, speech_start=1.6,
                                          speech_ratio=2.6)
            enh = np.zeros_like(noisy)
            for i in range(0, len(noisy), 3200):
                enh[i:i + 3200] = ns.process(noisy[i:i + 3200])
            for label, data, counter in (("raw", noisy, "raw"), ("enh", enh, "enh")):
                det.reset()
                hit = None
                pcm = to_pcm(data)
                for i in range(0, len(pcm), 3200):
                    h = det.feed(pcm[i:i + 3200])
                    if h:
                        hit = h
                        break
                if hit:
                    if counter == "raw":
                        hit_raw += 1
                    else:
                        hit_enh += 1
        total = len(files)
        better = hit_enh >= hit_raw
        ok = ok and better
        print(f"  SNR {snr_db:4.0f} dB：原始 {hit_raw}/{total} → 降噪后 {hit_enh}/{total}")
    print(f"  NS(唤醒): {'PASS' if ok else 'FAIL'}")
    return ok


def test_ns_atten() -> bool:
    print("\n== 4. 降噪量（纯噪声输入）==")
    noise = (RNG.standard_normal(SR * 2).astype(np.float32) * 0.02)
    ns = frontend.NoiseSuppressor()
    out = np.zeros_like(noise)
    for i in range(0, len(noise), 3200):
        out[i:i + 3200] = ns.process(noise[i:i + 3200])
    att = rms_db(noise) - rms_db(out)
    ok = att >= 10.0
    print(f"  输入 {rms_db(noise):6.1f} dBFS → 输出 {rms_db(out):6.1f} dBFS，"
          f"降噪量 {att:5.1f} dB  {'OK' if ok else 'FAIL'}")
    print(f"  NS(降噪量): {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    results = [test_agc(), test_ns_cer(), test_ns_kws(), test_ns_atten()]
    print("\n===== 汇总 =====")
    names = ["AGC 电平拉齐", "NS 降噪 CER", "NS 唤醒命中", "NS 降噪量"]
    for name, ok in zip(names, results):
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
