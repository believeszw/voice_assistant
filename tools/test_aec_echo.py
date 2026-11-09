"""AEC 强回声实验：合成回声（线性/混响/非线性）+ 真实声学两档。

背景：之前只测了「单延迟线性回声」，ERLE 38.2 dB 不代表真实房间。
本脚本补三件事：
1) 用合成 RIR 造早期反射 + 混响尾，看 AEC3 在混响下的 ERLE 退化；
2) 加扬声器非线性（tanh 饱和），看非线性回声的影响；
3) 真实声学：把 16k 语音拉满音量从输出设备播放、麦克风 16k 录音，
   按互相关对齐后测真实回声耦合比与 AEC3 的 ERLE。

用法：
    python tools/test_aec_echo.py                # 合成部分
    python tools/test_aec_echo.py --real         # 追加真实声学
"""

from __future__ import annotations

import argparse
import sys
import threading
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aec3 import AEC3  # noqa: E402

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - 仅真实声学部分需要
    sd = None

SR = 16000
FRAME = 160  # AEC3 只支持 10ms 帧
WAV_DIR = Path(__file__).parent / "wav"


# ---------------------------------------------------------------- 工具函数
def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return resample(x, rate, SR)


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x.astype(np.float32)
    n = int(len(x) * dst / src)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def fft_conv(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    n = len(x) + len(h) - 1
    nfft = 1 << int(np.ceil(np.log2(n)))
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)[: len(x)]
    return y.astype(np.float32)


def make_rir(delay: int = 1280, rt60: float = 0.0, seed: int = 7) -> np.ndarray:
    """合成 RIR：直达 + 几根早期反射 + 指数衰减噪声尾（rt60=0 表示纯直达）。"""
    length = max(delay + 64, int(SR * max(rt60, 0.02)) + delay)
    h = np.zeros(length, dtype=np.float32)
    h[delay] = 1.0
    for ms, g in ((18, 0.32), (37, 0.22), (61, 0.15), (88, 0.10)):
        idx = delay + int(SR * ms / 1000)
        if idx < length:
            h[idx] += g
    if rt60 > 0:
        rng = np.random.default_rng(seed)
        tail_len = int(SR * rt60)
        tail = rng.standard_normal(tail_len).astype(np.float32)
        env = np.exp(-6.9078 * np.arange(tail_len) / tail_len)  # -60dB @ rt60
        tail = (tail * env * 0.22).astype(np.float32)
        s = delay + int(SR * 0.003)
        h[s:s + tail_len] += tail[: max(0, min(tail_len, length - s))]
    # 归一化到单位能量：回声能量≈直达声能量，再乘 0.35 得到约 -9dB 耦合比
    h /= np.sqrt(np.sum(h ** 2) + 1e-12)
    return h.astype(np.float32)


def build_far(seconds: float = 4.7) -> np.ndarray:
    a = read_wav(WAV_DIR / "case_1.wav")
    b = read_wav(WAV_DIR / "case_6.wav")
    one = np.concatenate([a, np.zeros(int(SR * 0.4), np.float32), b])
    reps = max(1, int(np.ceil(seconds * SR / len(one))))
    far = np.tile(one, reps)[: int(seconds * SR)]
    pad = (-len(far)) % FRAME
    return np.concatenate([far, np.zeros(pad, np.float32)])


def process_aec3(near: np.ndarray, far: np.ndarray) -> tuple[np.ndarray, float]:
    aec = AEC3()
    out = np.zeros_like(near)
    for i in range(0, len(near) - FRAME + 1, FRAME):
        o, _ = aec.process(near[i:i + FRAME], far[i:i + FRAME])
        out[i:i + FRAME] = np.round(o * 32768.0).astype(np.int16) / 32768.0
    return out, aec.erle


def erle_db(near_echo: np.ndarray, out: np.ndarray, skip_s: float = 0.6) -> float:
    s = int(SR * skip_s)
    ref = near_echo[s:]
    res = out[s:]
    return float(10 * np.log10((np.mean(ref ** 2) + 1e-12) / (np.mean(res ** 2) + 1e-12)))


def db(x: float) -> float:
    return float(10 * np.log10(x + 1e-12))


# ---------------------------------------------------------------- 合成场景
def run_synthetic() -> list[tuple[str, dict]]:
    far = build_far()
    rng = np.random.default_rng(42)
    noise = rng.standard_normal(len(far)).astype(np.float32) * 0.0015
    results: list[tuple[str, dict]] = []

    def measure(name: str, echo: np.ndarray, near_extra: np.ndarray | None = None):
        near = echo + noise
        if near_extra is not None:
            near = near + near_extra
        out, _ = process_aec3(near.astype(np.float32), far)
        near_echo = echo + noise
        results.append((
            name,
            {
                "coupling_db": db(np.mean(near_echo ** 2) / (np.mean(far ** 2) + 1e-12)),
                "erle_db": erle_db(near_echo, out),
            },
        ))

    echo0 = np.concatenate([np.zeros(1280, np.float32), far[:-1280]]) * 0.35
    measure("S0 线性单延迟 (80ms, 0.35)", echo0)

    for rt, name in ((0.3, "S1 混响 RT60=0.3s"), (0.6, "S2 混响 RT60=0.6s")):
        measure(name, fft_conv(far, make_rir(rt60=rt)) * 0.35)

    measure("S3 非线性 tanh(drive=6)", np.tanh(echo0 * 6.0) / 6.0)

    echo_rev = fft_conv(far, make_rir(rt60=0.6)) * 0.35
    echo_both = np.tanh(echo_rev * 6.0) / 6.0
    measure("S4 混响0.6s + 非线性", echo_both)

    user = read_wav(WAV_DIR / "case_5.wav")
    near_extra = np.zeros(len(far), np.float32)
    st = int(SR * 1.6)
    seg = user[: min(len(user), len(far) - st)] * 0.12
    near_extra[st: st + len(seg)] = seg
    measure("S5 混响+非线性+双讲", echo_both, near_extra)

    return results


# ---------------------------------------------------------------- 真实声学
def device_index(name_part: str) -> int | None:
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0 and name_part.lower() in d["name"].lower():
            return i
    return None


def _can_play(dev: int, rate: int) -> bool:
    try:
        with sd.OutputStream(samplerate=rate, channels=1, dtype="int16",
                             blocksize=FRAME, device=dev):
            return True
    except Exception:
        return False


def _record_with_playback(far16: np.ndarray, dev: int, play_rate: int) -> tuple[np.ndarray, bool]:
    """把 far16 重采样到 play_rate 播出去，同时用麦克风 16k 录音。"""
    far = resample(far16, SR, play_rate)
    far = far / (float(np.max(np.abs(far))) + 1e-9) * 0.95
    rec = np.zeros(len(far16), np.float32)
    stop = threading.Event()
    ok = {"v": True}

    def player():
        try:
            with sd.OutputStream(samplerate=play_rate, channels=1, dtype="int16",
                                 blocksize=FRAME, device=dev) as st:
                pos = 0
                while pos < len(far) and not stop.is_set():
                    seg = far[pos:pos + FRAME]
                    buf = np.zeros(FRAME, np.float32)
                    buf[: len(seg)] = seg
                    st.write(np.clip(buf * 32768, -32768, 32767).astype(np.int16))
                    pos += FRAME
        except Exception as exc:  # pragma: no cover
            print(f"[real] 播放失败 device={dev} rate={play_rate}: {exc}")
            ok["v"] = False
            stop.set()

    th = threading.Thread(target=player, daemon=True)
    th.start()
    try:
        with sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                            blocksize=FRAME) as st:
            pos = 0
            while pos < len(far16):
                data, _ = st.read(FRAME)
                rec[pos:pos + FRAME] = data[:, 0] / 32768.0
                pos += FRAME
    finally:
        stop.set()
        th.join(timeout=2)
    return rec, ok["v"]


def run_real(seconds: float = 9.0) -> list[tuple[str, dict]]:
    if sd is None:
        print("sounddevice 不可用，跳过真实声学")
        return []
    far = build_far(seconds)

    cands: list[tuple[str, int]] = [("默认输出", sd.default.device[1])]
    for _api_i, api in enumerate(sd.query_hostapis()):
        if "WASAPI" in api["name"]:
            d = api["default_output_device"]
            if d is not None and d >= 0 and all(d != c[1] for c in cands):
                cands.append(("WASAPI 默认输出", int(d)))
    idx = device_index("Realtek")
    if idx is not None and all(idx != c[1] for c in cands):
        cands.append(("Realtek 扬声器", idx))

    results: list[tuple[str, dict]] = []
    for label, dev in cands:
        info = sd.query_devices(dev)
        default_rate = int(round(float(info.get("default_samplerate") or 48000)))
        rec, ok, used_rate = None, False, 0
        for rate in dict.fromkeys([16000, default_rate, 48000]):
            if not _can_play(dev, rate):
                print(f"[real] {label} 打不开 @{rate}Hz，换下一个")
                continue
            print(f"[real] {label} (device={dev}) 播放 {len(far)/SR:.1f}s @ {rate}Hz ...")
            rec, ok = _record_with_playback(far, dev, rate)
            used_rate = rate
            if ok:
                break
        if not ok or rec is None:
            continue

        # 对齐：rec[t] ≈ g * far[t-lag]，把 far 前补 lag 个零后再喂 AEC3
        x = rec.astype(np.float64)
        y = far.astype(np.float64)
        nfft = 1 << int(np.ceil(np.log2(len(x) + len(y))))
        cc = np.fft.irfft(np.fft.rfft(x, nfft) * np.conj(np.fft.rfft(y, nfft)), nfft)
        lag = int(np.argmax(cc[: int(SR * 0.8)]))
        if lag <= 0 or lag >= len(far) - 100:
            print(f"[real] {label} 对齐失败 lag={lag}，跳过")
            continue
        far_al = np.concatenate([np.zeros(lag, np.float32), far]).astype(np.float32)

        coupling = db(np.mean(rec[lag:] ** 2) / (np.mean(far_al[lag:] ** 2) + 1e-12))
        out, _ = process_aec3(rec, far_al[: len(rec)])
        results.append((
            f"R {label}",
            {
                "delay": lag,
                "rate": used_rate,
                "coupling_db": coupling,
                "erle_db": erle_db(rec, out, skip_s=1.5),
            },
        ))
    return results


# ---------------------------------------------------------------- 入口
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="追加真实声学")
    args = ap.parse_args()

    rows = run_synthetic()
    if args.real:
        rows += run_real()

    print("\n== AEC 强回声实验 ==")
    print(f"{'场景':<28} {'回声/近端':>10} {'ERLE':>8} {'延迟':>6}")
    for name, r in rows:
        delay = f"{r['delay']:>6}" if "delay" in r else "     -"
        print(f"{name:<28} {r['coupling_db']:>9.1f}dB {r['erle_db']:>7.1f}dB {delay}")


if __name__ == "__main__":
    main()
