"""端侧 TTS 可懂度回环：TTS 合成 → SenseVoice 识别 → 字符错误率（CER）。

用途：客观衡量「离线合成的声音还能不能听懂」，并对比 Piper / sherpa VITS 两个后端。
用法：
    C:\\va-venv\\Scripts\\python.exe tools\\test_tts_asr_roundtrip.py            # 自动后端
    $env:TTS_LOCAL_BACKEND="piper"; python tools/test_tts_asr_roundtrip.py      # 指定后端
输出：tools/test_tts_asr_roundtrip_{backend}.out
"""
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import sherpa_onnx  # noqa: E402
import tts_local  # noqa: E402

SENSE_DIR = BASE / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
LINES = []

SENTENCES = [
    "现在时间下午三点二十分",
    "音量已经调到百分之五十",
    "已打开记事本",
    "正在为你查询请稍等",
    "我有点热能把空调开到二十四度吗",
    "打开哔哩哔哩",
    "把浏览器给我整出来",
    "查一下明天天气",
    "退出助手",
    "讲个笑话吧",
]


def log(msg=""):
    print(msg, flush=True)
    LINES.append(str(msg))


def norm(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;“”‘’\"'（）()]", "", text or "")


def cer(ref: str, hyp: str) -> float:
    ref, hyp = norm(ref), norm(hyp)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


def build_asr():
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(SENSE_DIR / "model.int8.onnx"),
        tokens=str(SENSE_DIR / "tokens.txt"),
        use_itn=False,
        num_threads=2,
        debug=False,
    )
    return rec


def main():
    backend = tts_local.backend_name()
    if tts_local.available():
        tts_local.warmup()
    backend = tts_local.backend_name() or "unknown"
    out = BASE / "tools" / f"test_tts_asr_roundtrip_{backend}.out"
    log(f"TTS 后端={backend} sr={tts_local.sample_rate()} err={tts_local.error()}")

    t0 = time.perf_counter()
    rec = build_asr()
    asr_load_ms = (time.perf_counter() - t0) * 1000
    log(f"SenseVoice 加载 {asr_load_ms:.0f}ms")

    total_cer = 0.0
    tts_times = []
    log("")
    log(f"{'#':>2} {'TTS ms':>7} {'CER':>6}  原文 / 识别")
    for i, text in enumerate(SENTENCES, 1):
        data = tts_local.synth_wav(text)
        tts_times.append(tts_local.last_stats().get("synth_ms", 0.0))
        dur = len(data) / 2 / max(tts_local.sample_rate(), 1)
        pcm = np.frombuffer(data[44:], dtype=np.int16).astype(np.float32) / 32768.0
        stream = rec.create_stream()
        stream.accept_waveform(tts_local.sample_rate(), pcm)
        rec.decode_stream(stream)
        hyp = stream.result.text.strip()
        c = cer(text, hyp)
        total_cer += c
        log(f"{i:>2} {tts_local.last_stats().get('synth_ms', 0):>7.0f} {c:>6.3f}  {text}  →  {hyp}  ({dur:.2f}s)")

    log("")
    log(f"平均 CER = {total_cer / len(SENTENCES):.3f}  "
        f"（Piper 22050Hz / espeak-ng 音素；识别用 SenseVoice int8）")
    log(f"TTS 合成耗时: " + ", ".join(f"{t:.0f}" for t in tts_times) + " ms")
    out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    log(f"结果已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
