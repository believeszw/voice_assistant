"""集成测试：播放期间被用户打断（barge-in）的整条链路。

不依赖真实声卡：用 test_frontend 的合成场景回放麦克风数据，
假 Speaker 模拟「正在播报」，假 Mic 按 50ms 实时出块。
"""
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_frontend as T  # noqa: E402
import assistant as A  # noqa: E402

BLOCK = T.BLOCK  # 800 samples @16k = 50ms


class FakeMic:
    def __init__(self, near: np.ndarray):
        self.blocks = [near[i:i + BLOCK] for i in range(0, len(near), BLOCK)]
        self.i = 0

    def read(self, timeout=0.05):
        if self.i >= len(self.blocks):
            return None
        time.sleep(BLOCK / T.SR)
        b = self.blocks[self.i]
        self.i += 1
        return (b * 32768).astype(np.int16).tobytes()

    def flush(self):
        self.i = 0


class FakeSpeaker:
    """播报两秒，到点自动结束；被打断则立即结束。"""

    def __init__(self, far_bytes: bytes, duration=2.0):
        self.far_sink = None
        self.far_bytes = far_bytes
        self.duration = duration
        self.stopped = False
        self.paused = False
        self._done = threading.Event()

    def say_async(self, text):
        done = self._done
        done.clear()

        def run():
            if self.far_sink:
                self.far_sink(self.far_bytes)
            end = time.time() + self.duration
            while time.time() < end and not self.stopped:
                if self.paused:          # 暂停时冻结倒计时
                    end += 0.02
                time.sleep(0.02)
            done.set()

        threading.Thread(target=run, daemon=True).start()
        return done

    def say(self, text):
        self.say_async(text).wait()

    def playing(self):
        return not self._done.is_set()

    def pause(self):
        if self._done.is_set():
            return False
        self.paused = True
        return True

    def resume(self):
        self.paused = False

    def discard(self):
        self.stopped = True
        self.paused = False
        self._done.set()

    def stop(self):
        self.stopped = True
        self._done.set()

    def shutdown(self):
        pass


fe, near, echo, clean, probs, actives, barges = T.run(True)
far = echo / 0.35  # 反推参考信号（echo = far*0.35 + noise）

bot = A.Assistant(text_mode=False, dry_run=True, use_hotkey=False, use_wake=False)
bot.cloud_tts = True
bot.speaker = FakeSpeaker((np.clip(far, -1, 1) * 32768).astype(np.int16).tobytes())
bot.speaker.far_sink = bot.fe.push_far
bot._mic = FakeMic(near)

t0 = time.time()
bot.say("这是一段比较长的播报，用来测试用户打断。")
elapsed = time.time() - t0
print(f"播报时长: {elapsed:.2f}s  (speaker.stopped={bot.speaker.stopped})")
print(f"state={bot.state} interrupted={bot._interrupted}")

# 打断时说的话必须被完整接住：预录长度 + 能否识别出内容
pre = bot._pre_pcm or b""
pre_secs = len(pre) / (T.SR * 2)
pre_text = ""
if pre:
    try:
        pre_text = A.asr.transcribe_pcm(pre)
    except Exception as exc:  # pragma: no cover
        pre_text = f"<{exc}>"
print(f"预录: {pre_secs:.2f}s, 识别={pre_text!r}")

ok = (bot.speaker.stopped and bot._interrupted and bot.state == "INTERRUPTED"
      and pre_secs >= 1.0 and bool(pre_text.strip()))
print("PASS" if ok else "FAIL")
