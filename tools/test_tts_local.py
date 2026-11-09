"""端侧 TTS 自测（Piper 首选 / sherpa 兜底）：加载、首块延迟、整句合成 RTF、流式分块。

用法：C:\\va-venv\\Scripts\\python.exe tools\\test_tts_local.py
输出：tools/test_tts_local.out（UTF-8），样本 wav 存 tools/_tts_sample_*.wav
"""
import statistics
import sys
import time
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import tts_local  # noqa: E402

OUT = BASE / "tools" / "test_tts_local.out"
LINES = []

SENTENCES = [
    "现在时间下午三点二十分",
    "音量已经调到百分之五十",
    "已打开记事本",
    "正在为你查询，请稍等",
    "讲个笑话吧，从前有一只程序猿",
    "空调温度不支持，请说出音量或打开应用",
]


def log(msg=""):
    print(msg, flush=True)
    LINES.append(str(msg))


def wav_duration(data: bytes) -> tuple:
    tmp = BASE / "tools" / "_tts_probe.wav"
    tmp.write_bytes(data)
    with wave.open(str(tmp), "rb") as fh:
        return fh.getframerate(), fh.getnframes() / fh.getframerate(), fh.getnchannels(), fh.getsampwidth()


def main():
    t0 = time.perf_counter()
    ok = tts_local.warmup()
    load_ms = (time.perf_counter() - t0) * 1000
    log(f"warmup={ok} backend={tts_local.backend_name()} sr={tts_local.sample_rate()} "
        f"load+预热={load_ms:.0f}ms err={tts_local.error()}")
    if not ok:
        OUT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
        return 1

    # 流式首块延迟（Piper 真流式；sherpa 退化为整句）
    text = SENTENCES[0]
    t0 = time.perf_counter()
    first_ms = 0.0
    total_bytes = 0
    chunks = 0
    for pcm in tts_local.stream(text):
        if first_ms == 0.0:
            first_ms = (time.perf_counter() - t0) * 1000
        total_bytes += len(pcm)
        chunks += 1
    total_ms = (time.perf_counter() - t0) * 1000
    dur = total_bytes / 2 / tts_local.sample_rate()
    log(f"流式: 首块 {first_ms:.0f}ms  全句 {total_ms:.0f}ms  块数 {chunks}  "
        f"音频 {dur:.2f}s  RTF {total_ms / 1000 / dur:.2f}")

    times = []
    log("")
    log(f"{'#':>2} {'合成ms':>7} {'音频s':>6} {'RTF':>6}  文本")
    for i, text in enumerate(SENTENCES, 1):
        t = time.perf_counter()
        data = tts_local.synth_wav(text)
        ms = (time.perf_counter() - t) * 1000
        times.append(ms)
        rate, dur, ch, width = wav_duration(data)
        rtf = ms / 1000.0 / dur if dur else 0
        log(f"{i:>2} {ms:>7.0f} {dur:>6.2f} {rtf:>6.2f}  {text}  ({rate}Hz/{ch}ch/{width * 8}bit)")
        (BASE / "tools" / f"_tts_sample_{i}.wav").write_bytes(data)

    times.sort()
    p50 = statistics.median(times)
    log("")
    log(f"整句 P50={p50:.0f}ms  max={times[-1]:.0f}ms  backend={tts_local.backend_name()}")
    log(f"stats={tts_local.last_stats()}")

    OUT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    log(f"\n结果已写入 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
