"""真实声卡验收：播报期间没人说话时不应误打断；唤醒回应短句的延迟。

用法：python tools/test_barge_false.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio  # noqa: E402
import llm  # noqa: E402
from frontend import AudioFrontend  # noqa: E402
from tts import Speaker  # noqa: E402


def main():
    text = ("这是一段比较长的播报，用来验证播报期间会不会被自己的声音误打断，"
            "同时也检查一下播报会不会中途停。")
    try:
        wav = llm.tts_wav(text)
    except Exception as exc:
        print("云端 TTS 不可用，跳过:", str(exc)[:120])
        return 0
    if not wav:
        print("云端 TTS 未返回音频，跳过")
        return 0

    fe = AudioFrontend()
    fe.reset()
    spk = Speaker()
    spk.far_sink = fe.push_far
    mic = audio.Mic()
    mic.start()

    barge = 0
    t0 = time.time()
    done = spk.say_async(text)
    try:
        while not done.is_set():
            block = mic.read(0.05)
            if not block:
                continue
            fe.process(block)
            if fe.barge_in:
                barge += 1
    finally:
        mic.stop()
        fe.reset()
    dur = time.time() - t0

    # 唤醒回应短句：走本地 SAPI，应该明显快于云端合成（约 1 s）
    t1 = time.time()
    spk.say_quick("我在")
    quick = time.time() - t1
    spk.shutdown()

    print(f"播报时长: {dur:.2f}s  误打断次数: {barge}  (期望 0)")
    print(f"唤醒回应耗时: {quick:.2f}s  (预生成音频约 1.0s，期望 < 1.35s)")
    ok = barge == 0 and dur > 2.0 and quick < 1.35
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
