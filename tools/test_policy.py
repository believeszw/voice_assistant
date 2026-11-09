"""验收「端侧优先、云端为辅」识别策略。

三个数据集：干净合成 / SNR 10 dB / SNR 5 dB。
对每条音频：
  1) 端侧双遍识别（流式 Paraformer + SenseVoice），记录耗时；
  2) 按生产策略判断是否要云端兜底（结果为空或字数不足）；
  3) 需要时调用云端 MiMo 重听，记录多花的时间。
输出：端侧 CER、兜底率、云端调用率、策略后 CER、平均端到端耗时。
"""

import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import asr_local  # noqa: E402
import config  # noqa: E402
import intents  # noqa: E402
import llm  # noqa: E402
from test_sherpa import TEXTS, _norm, cer  # noqa: E402

DATASETS = [
    ("clean", Path(__file__).resolve().parent / "wav", "case_{}.wav"),
    ("10db", Path(__file__).resolve().parent / "farwav_10db", "case_{}.wav"),
    ("5db", Path(__file__).resolve().parent / "farwav_5db", "case_{}.wav"),
    ("0db", Path(__file__).resolve().parent / "farwav_0db", "case_{}.wav"),
]


def load(path: Path):
    with wave.open(str(path), "rb") as w:
        ch, sr = w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    use_cloud = "--with-cloud" in sys.argv
    engine = asr_local.TwoPassASR()
    print(f"端侧双遍可用: {engine.available()} {engine.err}")
    print(f"策略: ASR_LOCAL_FIRST={config.ASR_LOCAL_FIRST} 云端兜底={use_cloud and config.ASR_CLOUD_FALLBACK}")

    for name, folder, pattern in DATASETS:
        cer_local, cer_final, fallback, cloud_used = [], [], 0, 0
        t_finish, t_cloud = [], []
        unknown_cnt = 0
        for i, ref in enumerate(TEXTS[:12]):
            path = folder / pattern.format(i)
            if not path.exists():
                continue
            pcm = load(path)
            engine.start()
            for off in range(0, len(pcm), 1600):  # 50ms 一块
                engine.feed(pcm[off:off + 1600])
            t0 = time.time()
            text, eng = engine.finish()
            t_finish.append(time.time() - t0)
            cer_local.append(cer(ref, text))
            unknown = intents.parse(text).get("action") == "unknown"
            too_short = (not text.strip()) or len(text.strip()) < config.ASR_LOCAL_MIN_CHARS
            # 生产策略：本地没听清，或本地文本解析不出意图，才上云端重听
            need = too_short or (unknown and config.ASR_CLOUD_RETRY_ON_UNKNOWN)
            if unknown:
                unknown_cnt += 1
            if need and use_cloud and (config.ASR_CLOUD_FALLBACK or config.ASR_CLOUD_RETRY_ON_UNKNOWN):
                fallback += 1
                try:
                    t1 = time.time()
                    cloud_text = llm.asr_pcm(pcm, 16000) or ""
                    t_cloud.append(time.time() - t1)
                    # 只有云端文本能解析出明确意图时才采纳（与生产策略一致）
                    if cloud_text.strip():
                        cloud_used += 1
                        if intents.parse(cloud_text).get("action") != "unknown":
                            text = cloud_text
                except Exception as exc:  # noqa: BLE001
                    print("  云端失败:", str(exc)[:80])
            cer_final.append(cer(ref, text))
        n = len(cer_local)
        if not n:
            continue
        avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
        print(f"\n[{name}] n={n}")
        print(f"  端侧 CER           : {avg(cer_local):.3f}")
        print(f"  策略后 CER         : {avg(cer_final):.3f}")
        print(f"  本地意图 unknown   : {unknown_cnt}/{n}")
        print(f"  云端重听触发       : {fallback}/{n}")
        print(f"  云端稳定返回       : {cloud_used}/{fallback if fallback else 0}")
        print(f"  端侧句尾耗时均值   : {avg(t_finish) * 1000:.0f} ms")
        if t_cloud:
            print(f"  云端兜底耗时均值   : {avg(t_cloud) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
