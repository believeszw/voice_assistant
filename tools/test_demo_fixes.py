"""演示脚本三处体验问题的回归测试。

对应真实运行日志里的三个失败点：
1) 唤醒词被模糊识别成「你好小姐」，残余「姐」被当指令执行；
2) 噪声被识别成「Yeah。」，被当成闲聊指令、白吃一轮对话；
3) 播报自己的尾音在「暂停→确认」窗口里被当成用户插话，误打断。

通过线：全部 PASS。
"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assistant as A  # noqa: E402
from frontend import AudioFrontend  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# ---------- 1) 唤醒词残余 ----------
rest = A.Assistant.__dict__["_strip_wake"]
inst = A.Assistant(text_mode=True, use_hotkey=False, use_wake=False)
check("strip_wake('你好小姐') 应为空", rest(inst, "你好小姐") == "",
      repr(rest(inst, "你好小姐")))
check("strip_wake('你好小助手') 应为空", rest(inst, "你好小助手") == "")
check("strip_wake('小助手，现在几点了') 应保留指令",
      rest(inst, "小助手，现在几点了") == "现在几点了",
      repr(rest(inst, "小助手，现在几点了")))
check("_is_noise('姐') 应为噪声", A._is_noise("姐"))
check("_is_noise('Yeah。') 应为噪声", A._is_noise("Yeah。"))
check("_is_noise('嗯。') 应为噪声", A._is_noise("嗯。"))
check("_is_noise('打开记事本') 不是噪声", not A._is_noise("打开记事本"))
check("_is_noise('') 视为噪声", A._is_noise(""))

# ---------- 3a) 误打断：播报尾音（暂停后前 150ms）不算确认 ----------
class FakeMic:
    """前 loud_first 个块很响（模拟播放尾巴），之后安静。"""

    def __init__(self, loud_first=3, loud_rms=0.12):
        self.left = loud_first
        self.loud_rms = loud_rms
        self.calls = 0

    def flush(self):
        pass

    def read(self, timeout=0.05):
        time.sleep(0.05)  # 模拟真实 50ms 一块
        self.calls += 1
        n = int(16000 * 0.05)
        if self.left > 0:
            self.left -= 1
            sig = np.full(n, self.loud_rms, dtype=np.float32)
        else:
            sig = np.zeros(n, dtype=np.float32)
        return (np.clip(sig, -1, 1) * 32768).astype(np.int16).tobytes()


m = FakeMic(loud_first=4)
inst._mic = m
confirmed, pcm = inst._confirm_barge(0.30)
check("暂停尾音不应被确认为打断", confirmed is False, f"confirmed={confirmed}")

m = FakeMic(loud_first=0)
inst._mic = m


class LoudMic(FakeMic):
    def __init__(self):
        super().__init__(loud_first=99)


inst._mic = LoudMic()
confirmed, pcm = inst._confirm_barge(0.30)
check("确认窗口里真有人说话应确认", confirmed is True, f"confirmed={confirmed}")
check("确认窗口音频应保留", len(pcm) > 0, f"pcm={len(pcm)}B")
inst._mic = None

# ---------- 3b) 只有能量尖峰、没有语音时前端不应 barge ----------
SR = 16000
BLOCK = 800


def barge_for(sig):
    fe = AudioFrontend()
    fe.reset()
    for i in range(0, len(sig) - BLOCK, BLOCK):
        fe.process((np.clip(sig[i:i + BLOCK], -1, 1) * 32768).astype(np.int16).tobytes())
        if fe.barge_in:
            return True, fe.barge_evidence
    return False, fe.barge_evidence


rng = np.random.default_rng(3)
n = int(3.0 * SR)
quiet = rng.normal(0, 0.0015, n).astype(np.float32)
spike = quiet.copy()
spike[int(1.0 * SR):int(1.12 * SR)] += 0.30  # 12 个 50ms 块里的一个响尖峰
spike[int(1.3 * SR):int(1.42 * SR)] += 0.30
hit, ev = barge_for(spike)
check("无声语音尖峰不应触发 barge", not hit, ev)

# 真人说话（VAD 能认出）仍应触发
wav = np.fromfile(str(Path(__file__).resolve().parent / "wav" / "case_5.wav"),
                  dtype=np.int16)[22:]  # 跳过 wav 头
speech = wav.astype(np.float32) / 32768.0
speech = speech / max(1e-6, float(np.sqrt(np.mean(speech ** 2))))
near = quiet.copy()
seg = speech[:int(1.2 * SR)] * 0.12
near[int(1.0 * SR):int(1.0 * SR) + len(seg)] += seg
hit, ev = barge_for(near)
print(f"[参考] 真人语音 rms=0.12 时 barge={hit}（{ev}）")

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
