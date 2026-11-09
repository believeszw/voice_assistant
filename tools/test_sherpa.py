"""第 3 步冒烟：sherpa-onnx 流式 Paraformer + 句尾 SenseVoice 校正效果与耗时。

用 tools/wav/case_*.wav（SAPI 合成、已知文本）比较：
  1) 流式 Paraformer：模拟 0.2s 分块喂入，记录首字延迟与最终文本；
  2) SenseVoice 离线：整段识别，记录耗时；
  3) 用字符级编辑距离算 CER。
"""

import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
WAV_DIR = Path(__file__).resolve().parent / "wav"
SR = 16000

TEXTS = [
    "小助手",
    "小助手打开记事本",
    "打开记事本",
    "现在几点了",
    "把音量调大一点",
    "下一首",
    "截个屏",
    "关闭计算器",
    "音量调到五十",
    "搜索天气",
    "显示桌面",
    "锁屏",
]


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        width = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    assert width == 2
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        duration = len(data) / sr
        n = int(duration * SR)
        x_old = np.linspace(0, duration, len(data), endpoint=False)
        x_new = np.linspace(0, duration, n, endpoint=False)
        data = np.interp(x_new, x_old, data).astype(np.float32)
    return data


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn2num(m):
    s = m.group(0)
    if "十" not in s and "百" not in s:
        return "".join(str(_CN_DIGITS[c]) for c in s if c in _CN_DIGITS) or s
    # 处理 十/百：如 五十、一百二十、十五
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch == "十":
            section += (num or 1) * 10
            num = 0
        elif ch == "百":
            section += (num or 1) * 100
            num = 0
    return str(section + num)


def _norm(text: str) -> str:
    """去标点/空白，并把中文数字转成阿拉伯数字，便于公平比较 CER。"""
    import re

    text = re.sub(r"[零一二两三四五六七八九十百]+", _cn2num, text)
    return re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", text)


def cer(ref: str, hyp: str) -> float:
    ref = _norm(ref)
    hyp = _norm(hyp)
    if not ref:
        return 0.0 if not hyp else 1.0
    dp = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        ndp = [i]
        for j, hc in enumerate(hyp, 1):
            ndp.append(min(dp[j] + 1, ndp[j - 1] + 1, dp[j - 1] + (rc != hc)))
        dp = ndp
    return dp[-1] / len(ref)


def make_streaming():
    import sherpa_onnx

    d = MODELS / "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
    return sherpa_onnx.OnlineRecognizer.from_paraformer(
        tokens=str(d / "tokens.txt"),
        encoder=str(d / "encoder.int8.onnx"),
        decoder=str(d / "decoder.int8.onnx" if (d / "decoder.int8.onnx").exists() else d / "decoder.onnx"),
        num_threads=2,
        sample_rate=SR,
        feature_dim=80,
        decoding_method="greedy_search",
        enable_endpoint_detection=False,
        debug=False,
    )


def make_sensevoice():
    import sherpa_onnx

    d = MODELS / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(d / "model.int8.onnx"),
        tokens=str(d / "tokens.txt"),
        num_threads=2,
        use_itn=True,
        debug=False,
    )


def run_streaming(rec, samples: np.ndarray, chunk=0.2):
    stream = rec.create_stream()
    first_text_at = None
    t0 = time.time()
    step = int(chunk * SR)
    for i in range(0, len(samples), step):
        stream.accept_waveform(SR, samples[i : i + step])
        while rec.is_ready(stream):
            rec.decode_stream(stream)
        partial = rec.get_result(stream)
        if partial and first_text_at is None:
            first_text_at = time.time() - t0
    # flush：补 0.5s 静音
    stream.accept_waveform(SR, np.zeros(SR // 2, dtype=np.float32))
    stream.input_finished()
    while rec.is_ready(stream):
        rec.decode_stream(stream)
    text = rec.get_result(stream)
    total = time.time() - t0
    return text, first_text_at, total


def run_offline(rec, samples: np.ndarray):
    t0 = time.time()
    stream = rec.create_stream()
    stream.accept_waveform(SR, samples)
    rec.decode_stream(stream)
    text = stream.result.text
    return text, time.time() - t0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    streaming = make_streaming()
    sensevoice = make_sensevoice()
    sys.path.insert(0, str(ROOT))
    from asr_local import TwoPassASR

    two_pass = TwoPassASR()
    print(f"[TwoPassASR] available={two_pass.available()} err={two_pass.err}")

    # Vosk 基线（现状用的本地小模型）
    sys.path.insert(0, str(ROOT))
    import asr as vosk_asr

    # 云端 MiMo（可选，--cloud 打开）
    use_cloud = "--cloud" in sys.argv
    if use_cloud:
        import llm

    # 数据集：默认用合成 wav；--mic 用外放->麦克风实录（远场，更接近真实）；
    # --dir <name> 用 tools 下指定的子目录（如 farwav_10db）
    use_mic = "--mic" in sys.argv
    dir_name = None
    if "--dir" in sys.argv:
        dir_name = sys.argv[sys.argv.index("--dir") + 1]
    if dir_name:
        wav_dir = Path(__file__).resolve().parent / dir_name
        file_of = lambda i: wav_dir / f"case_{i}.wav"
        print(f"[数据集] 指定目录: {wav_dir}")
    elif use_mic:
        wav_dir = Path(__file__).resolve().parent / "micwav"
        file_of = lambda i: wav_dir / f"mic_case_{i}.wav"
        print(f"[数据集] 远场实录: {wav_dir}")
    else:
        file_of = lambda i: WAV_DIR / f"case_{i}.wav"
        print(f"[数据集] 合成音频: {WAV_DIR}")

    rows = []
    for i, ref in enumerate(TEXTS):
        path = file_of(i)
        if not path.exists():
            print(f"missing {path}")
            continue
        samples = load_wav(path)
        dur = len(samples) / SR
        pcm_i16 = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
        st_text, first_at, st_time = run_streaming(streaming, samples)
        sv_text, sv_time = run_offline(sensevoice, samples)
        vosk_text = vosk_asr.transcribe_pcm(pcm_i16)
        cloud_text = ""
        if use_cloud:
            try:
                cloud_text = llm.asr_pcm(pcm_i16, SR) or ""
            except Exception as e:
                cloud_text = f"<err {str(e)[:40]}>"
        # 端侧双遍（按 100ms 块喂，模拟实时）
        tp_text, tp_engine, tp_first, tp_time = "", "none", None, 0.0
        if two_pass.available():
            two_pass.start()
            t0 = time.time()
            step = int(0.1 * SR)
            for j in range(0, len(samples), step):
                chunk = samples[j : j + step]
                pcm = (np.clip(chunk, -1, 1) * 32767).astype(np.int16).tobytes()
                part = two_pass.feed(pcm)
                if part and tp_first is None:
                    tp_first = time.time() - t0
            tp_text, tp_engine = two_pass.finish(b"")
            tp_time = time.time() - t0
        rows.append((ref, st_text, sv_text, tp_text, vosk_text, cloud_text, first_at, st_time, sv_time, tp_first, tp_time, dur))
        print(
            f"[{ref}] dur={dur:.2f}s\n"
            f"   vosk   : {vosk_text!r}  CER={cer(ref, vosk_text):.2f}\n"
            f"   stream : {st_text!r}  first={first_at if first_at is not None else -1:.2f}s total={st_time:.2f}s  CER={cer(ref, st_text):.2f}\n"
            f"   sense  : {sv_text!r}  time={sv_time:.2f}s  CER={cer(ref, sv_text):.2f}\n"
            f"   twopass: {tp_text!r} ({tp_engine})  first={tp_first if tp_first is not None else -1:.2f}s total={tp_time:.2f}s  CER={cer(ref, tp_text):.2f}"
            + (f"\n   cloud  : {cloud_text!r}  CER={cer(ref, cloud_text):.2f}" if use_cloud else "")
        )

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else float("nan")

    print("\n=== 汇总 ===")
    print(f"Vosk 平均 CER           : {avg([cer(r[0], r[4]) for r in rows]):.3f}")
    print(f"流式 Paraformer 平均 CER: {avg([cer(r[0], r[1]) for r in rows]):.3f}")
    print(f"SenseVoice 平均 CER     : {avg([cer(r[0], r[2]) for r in rows]):.3f}")
    print(f"端侧双遍平均 CER        : {avg([cer(r[0], r[3]) for r in rows]):.3f}")
    if use_cloud:
        print(f"云端 MiMo 平均 CER      : {avg([cer(r[0], r[5]) for r in rows]):.3f}")
    print(f"流式首字平均延迟        : {avg([r[6] for r in rows]):.3f}s")
    print(f"双遍首字平均延迟        : {avg([r[9] for r in rows]):.3f}s")
    print(f"双遍句尾总耗时均值      : {avg([r[10] for r in rows]):.3f}s")
    print(f"SenseVoice 耗时均值      : {avg([r[8] for r in rows]):.3f}s")


if __name__ == "__main__":
    main()
