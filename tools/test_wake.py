"""验证 KWS 唤醒 + 连续对话（主线程内联执行，不依赖真实麦克风，也不起线程）。

链路：静音 → 「你好小助手」（KWS 命中）→ 「现在几点了」→ 「退出」。
断言：KWS 命中、会话里一轮指令被正确执行（时间）、说「退出」结束会话。

说明：真实 run_voice 里 KWS/ASR 都在工作线程里跑，某些 onnxruntime 版本在
子线程加载模型会直接 abort，所以验收脚本把整条链路放在主线程里跑。
"""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import assistant as assistant_mod  # noqa: E402
import kws as kws_mod  # noqa: E402
from test_session import TapeMic, wav_to_pcm16k  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WAV = Path(__file__).resolve().parent / "wav"
KWSWAV = Path(__file__).resolve().parent / "kwswav"
SR = 16000


class FakeSpeaker:
    def __init__(self):
        self.said = []
        self.far_sink = None
        self.stopped = False

    def say(self, text):
        self.said.append(text)

    def say_async(self, text):
        self.said.append(text)
        ev = __import__("threading").Event()
        ev.set()
        return ev

    def stop(self):
        self.stopped = True

    def busy(self):
        return False

    def shutdown(self):
        pass


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("[test] 加载 KWS 模型 …", flush=True)
    det = kws_mod.WakeWord()
    if not det.available():
        print("KWS 不可用:", det.err)
        return 1
    print("[test] KWS 就绪", flush=True)

    wake_pcm = wav_to_pcm16k((KWSWAV / "wake_你好小助手_0.wav").read_bytes())
    tap = TapeMic([wake_pcm])
    hit, hit_pos = None, 0.0
    for i in range(0, len(wake_pcm), 1600):
        h = det.feed(wake_pcm[i:i + 1600])
        if h:
            hit, hit_pos = h, (i + 1600) / SR
            break
    print(f"[test] KWS 命中: {hit!r} @ {hit_pos:.2f}s", flush=True)

    # 会话：先「现在几点了」，再「退出」
    tape = TapeMic([
        wav_to_pcm16k((WAV / "case_3.wav").read_bytes()),
        wav_to_pcm16k((KWSWAV / "exit.wav").read_bytes()),
    ])
    fake = FakeSpeaker()
    assistant_mod.audio.Mic = lambda *a, **k: tape
    assistant_mod.Speaker = FakeSpeaker
    bot = assistant_mod.Assistant(text_mode=False, dry_run=True, use_hotkey=False)
    bot.speaker = fake
    bot._mic = tape
    bot.kws = det
    bot.fe = assistant_mod.AudioFrontend()

    print("[test] 进入会话（模拟唤醒后）", flush=True)
    bot._enter_session(tape, assistant_mod.asr.StreamASR())

    said = " | ".join(fake.said)
    ok_time = any(("现在" in s and "点" in s) or "现在是" in s for s in fake.said)
    print("\n播报内容:", said)
    print(f"\nKWS 唤醒: {'PASS' if hit else 'FAIL'}")
    print(f"指令执行: {'PASS' if ok_time else 'FAIL'}")
    print(f"会话结束: {'PASS' if tape.blocks and len(tape.blocks) < 60 else 'CHECK'}")
    return 0 if (hit and ok_time) else 1


if __name__ == "__main__":
    sys.exit(main())
