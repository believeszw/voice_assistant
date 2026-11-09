"""端到端（主线程）验证 run_voice 的唤醒→会话胶水。

与 test_wake.py 的区别：这里真的跑 Assistant.run_voice()（生产路径），
只是把麦克风换成 TapeMic，喂 [你好小助手] → [现在几点了] → [退出]，
并在会话结束后抛出 _Done 结束 run_voice 的常驻循环。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import assistant as assistant_mod  # noqa: E402
from test_session import TapeMic, wav_to_pcm16k  # noqa: E402
from test_wake import FakeSpeaker  # noqa: E402

WAV = Path(__file__).resolve().parent / "wav"
KWSWAV = Path(__file__).resolve().parent / "kwswav"


class _Done(Exception):
    pass


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    tape = TapeMic([
        wav_to_pcm16k((KWSWAV / "wake_你好小助手_0.wav").read_bytes()),
        wav_to_pcm16k((WAV / "case_3.wav").read_bytes()),   # 现在几点了
        wav_to_pcm16k((KWSWAV / "exit.wav").read_bytes()),  # 退出
    ])
    assistant_mod.audio.Mic = lambda *a, **k: tape
    assistant_mod.Speaker = FakeSpeaker
    fake = FakeSpeaker()

    bot = assistant_mod.Assistant(text_mode=False, dry_run=True, use_hotkey=False)
    bot.speaker = fake
    bot._mic = tape

    orig = bot._enter_session
    calls = {"n": 0}

    def wrapped(mic, stream, rest=""):
        calls["n"] += 1
        orig(mic, stream, rest)
        raise _Done()

    bot._enter_session = wrapped

    try:
        bot.run_voice()
    except _Done:
        pass

    said = " | ".join(fake.said)
    print("\n播报内容:", said)
    ok = calls["n"] == 1 and any(("现在" in s and "点" in s) for s in fake.said)
    print(f"\nrun_voice 唤醒→会话: {'PASS' if calls['n'] == 1 else 'FAIL'}（会话次数 {calls['n']}）")
    print(f"指令执行: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
