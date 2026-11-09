"""仿真测试：用合成的 wav 冒充麦克风输入，跑完整的唤醒 → 指令 → 执行链路。

不依赖真实声学环境（扬声器/麦克风距离），只验证逻辑。
用法：python tools/sim_test.py
"""

import io
import sys
import threading
import time
import wave
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assistant  # noqa: E402
import audio  # noqa: E402

WAV_DIR = Path(__file__).resolve().parent / "wav"


def load_16k(name: str) -> bytes:
    with wave.open(str(WAV_DIR / name), "rb") as wf:
        channels, sr = wf.getnchannels(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    data = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels)[:, 0]
    if sr != 16000:
        duration = len(data) / sr
        n = int(duration * 16000)
        x_old = np.linspace(0, duration, len(data), endpoint=False)
        x_new = np.linspace(0, duration, n, endpoint=False)
        data = np.interp(x_new, x_old, data).astype(np.int16)
    return data.tobytes()


class FakeMic:
    """按 50ms 块回放录音文件，块间 sleep 模拟实时。"""

    BLOCK = 800

    def __init__(self, *_, **__):
        silence_short = b"\x00\x00" * 800 * 30      # 1.5s
        silence_mid = b"\x00\x00" * 800 * 30
        silence_tail = b"\x00\x00" * 800 * 60        # 3s
        pcm = (silence_short + load_16k("e2e_wake.wav") + silence_mid
               + load_16k("case_3.wav") + silence_tail)
        self._blocks = [pcm[i:i + self.BLOCK * 2]
                        for i in range(0, len(pcm), self.BLOCK * 2)]
        self._i = 0

    def start(self):
        pass

    def stop(self):
        pass

    def flush(self):
        pass

    @property
    def name(self):
        return "FakeMic(合成语音)"

    def read(self, timeout: float = 0.5):
        if self._i >= len(self._blocks):
            raise SystemExit(0)
        block = self._blocks[self._i]
        self._i += 1
        time.sleep(0.05)
        return block


class SilentSpeaker:
    def __init__(self, *_, **__):
        pass

    def say(self, text: str):
        print(f"[助手] {text}", flush=True)

    def say_async(self, text: str):
        print(f"[助手] {text}", flush=True)

    def stop(self):
        pass

    def shutdown(self):
        pass


def main():
    assistant.audio.Mic = FakeMic
    assistant.Speaker = SilentSpeaker
    buf = io.StringIO()
    with redirect_stdout(buf):
        a = assistant.Assistant(use_hotkey=False)
        try:
            a.run_voice()
        except SystemExit:
            pass
    out = buf.getvalue()
    print(out)
    checks = {
        "唤醒命中": "唤醒词命中" in out,
        "指令识别": "现在几点了" in out,
        "回复时间": "现在是" in out,
    }
    print("=== 检查结果 ===")
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
