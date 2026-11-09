"""云端 TTS 可懂度与延迟回环：MiMo TTS 合成 → SenseVoice 识别 → CER。

与 test_tts_asr_roundtrip.py 用同一组句子，便于云端 / 端侧对比：
    C:\\va-venv\\Scripts\\python.exe tools\\test_cloud_tts_roundtrip.py
输出：tools/test_cloud_tts_roundtrip_cloud-mimo.out
"""
import io
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import llm  # noqa: E402
import sherpa_onnx  # noqa: E402

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
    return re.sub(r"[\s，。！？、,.!?：:；;“”‘’（）()]", "", text or "")


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


def main():
    if not llm.available():
        print("云端不可用（无 key 或 VOICE_OFFLINE=1）")
        return 2
    out = BASE / "tools" / "test_cloud_tts_roundtrip_cloud-mimo.out"
    log("云端 TTS = MiMo mimo-v2.5-tts，音色=冰糖；识别 = SenseVoice int8")
    t0 = time.perf_counter()
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(SENSE_DIR / "model.int8.onnx"),
        tokens=str(SENSE_DIR / "tokens.txt"),
        use_itn=False, num_threads=2, debug=False,
    )
    log(f"SenseVoice 加载 {(time.perf_counter() - t0) * 1000:.0f}ms")
    log("")
    log(f"{'#':>2} {'往返 ms':>8} {'CER':>6}  原文 / 识别")
    total_cer = 0.0
    times = []
    for i, text in enumerate(SENTENCES, 1):
        t1 = time.time()
        try:
            data = llm.tts_wav(text, timeout=10.0)
        except Exception as e:  # pragma: no cover
            log(f"{i:>2} ERR {e}")
            continue
        ms = (time.time() - t1) * 1000
        times.append(ms)
        with wave.open(io.BytesIO(data), "rb") as wf:
            rate, ch, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
        if width != 2:
            log(f"{i:>2} 不支持位宽 {width}")
            continue
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            pcm = pcm.reshape(-1, ch).mean(axis=1)
        stream = rec.create_stream()
        stream.accept_waveform(rate, pcm)
        rec.decode_stream(stream)
        hyp = stream.result.text.strip()
        c = cer(text, hyp)
        total_cer += c
        dur = len(pcm) / max(rate, 1)
        log(f"{i:>2} {ms:>8.0f} {c:>6.3f}  {text}  →  {hyp}  ({dur:.2f}s @{rate}Hz)")
    n = max(1, len(times))
    log("")
    log(f"平均 CER = {total_cer / n:.3f}")
    times_sorted = sorted(times)
    log(f"云端 TTS 往返 P50={times_sorted[len(times) // 2]:.0f}ms "
        f"min={min(times):.0f}ms max={max(times):.0f}ms（含网络+整句合成）")
    out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    log(f"结果已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
