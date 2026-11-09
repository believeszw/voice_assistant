"""轻量回声抑制（参考信号对齐 + 最小二乘增益）。

本机没有可用的 WebRTC AEC3 轮子（webrtc-audio-processing 只有源码包，要 MSVC 编译），
所以这里做工程化的替代方案，目标是把"自己的声音"从麦克风信号里压下去，够 VAD 在
播报时判断用户是否打断：

1. 延迟估计：GCC-PHAT 估计「播放 → 麦克风」延迟，稳定几票后锁定；
2. 回声估计：按锁定的延迟对齐参考信号，用最小二乘估一个增益 a（缓慢平滑），
   得到回声估计 a * far_delayed；
3. 残差：near - a * far_delayed，就是去回声后的信号；
4. 双讲检测（DTD）：残差能量相对基线明显抬升 → 用户开口，冻结增益并上报。

真实的非线性回声、房间反射需要 AEC3 级别的自适应滤波；本模块是"够用、可解释、
可测试"的工程折中，选型文档里已把 AEC3 列为量产首选、这是本机离线替代。
"""

from collections import deque

import numpy as np

SR = 16000
FRAME = 256


class AEC:
    def __init__(self, sr: int = SR, frame: int = FRAME,
                 mu: float = 0.25, dtd_ratio: float = 2.5):
        self.sr = sr
        self.B = frame
        self.mu = mu                # 增益平滑速度（保留接口，值越大跟得越快）
        self.dtd_ratio = dtd_ratio

        self._far_buf = np.zeros(0, dtype=np.float32)   # 参考信号累积（按延迟取块）
        # 环形缓冲留 2 秒：延迟估计要先攒够 1.5 秒数据再锁
        self._near_ring = deque(maxlen=max(16, sr * 2 // frame))
        self._far_ring = deque(maxlen=max(16, sr * 2 // frame))
        self._lag_hist = deque(maxlen=3)
        self._frames = 0
        self.delay = 0
        self._delay_locked = False

        self._gain = 0.0            # 当前增益估计
        self._near_pow = 1e-8
        self._far_pow = 1e-8
        self._res_hist = deque(maxlen=100)
        self._last_delay = 0
        self._dtd_freeze = 0
        self.dtd = False
        self.erle = 0.0

    # ------------------------------------------------------------------
    def _estimate_delay(self):
        if self._delay_locked:
            return
        win = int(self.sr * 0.4)  # 0.4 秒窗：覆盖本机约 0.31s 链路延迟，又能早点锁
        # 至少攒够 1.5 秒数据再估：刚起播时窗里只有很短的播放片段，容易锁到假延迟
        if len(self._near_ring) * self.B < int(self.sr * 0.4) \
                or len(self._far_ring) * self.B < int(self.sr * 0.4):
            return
        near = np.concatenate(list(self._near_ring))[-win:]
        far = np.concatenate(list(self._far_ring))[-win:]
        if float(np.mean(far ** 2)) < 1e-7 or float(np.mean(near ** 2)) < 1e-7:
            return
        spec = np.fft.rfft(near) * np.conj(np.fft.rfft(far))
        cc = np.fft.irfft(spec / (np.abs(spec) + 1e-9), win)
        max_lag = int(win * 0.9)  # 只接受正向滞后（回声晚于播放）
        lag = int(np.argmax(cc[:max_lag]))
        if lag <= 0:
            return
        # 峰值要明显高于平均，避免把噪声当成延迟
        if cc[lag] < 1.5 * float(np.mean(cc[:max_lag])) + 1e-6:
            return
        # 延迟不能超过参考缓冲，且对齐后要真有相关性，否则不锁
        if lag >= win - self.B:
            return
        ref0 = far[0:win - lag]
        near0 = near[lag:]
        m = min(len(ref0), len(near0))
        if m <= 0:
            return
        denom = (float(np.sqrt(np.dot(ref0[:m], ref0[:m])))
                 * float(np.sqrt(np.dot(near0[:m], near0[:m]))) + 1e-12)
        corr = float(np.dot(ref0[:m], near0[:m])) / denom
        if corr < 0.15:
            return
        self._lag_hist.append(lag)
        vals = sorted(self._lag_hist)
        if len(vals) == self._lag_hist.maxlen and (vals[-1] - vals[0]) <= 16:
            self.delay = int(vals[len(vals) // 2])
            self._delay_locked = True
            # 用锁定延迟的这段数据直接初始化增益：按 256 样本小块算最小二乘增益，
            # 取中位数，避免双讲/用户语音把初始增益带偏。
            d = min(self.delay, len(far) - 1, len(near) - 1)
            if d > 0:
                r0 = far[0:len(far) - d]
                n0 = near[d:]
                mm = min(len(r0), len(n0))
                gains = []
                for k in range(0, mm - 256, 256):
                    rk = r0[k:k + 256]
                    nk = n0[k:k + 256]
                    rp = float(np.dot(rk, rk))
                    if rp > 1e-6 and float(np.mean(rk ** 2)) > 1e-4:
                        gains.append(float(np.dot(nk, rk) / rp))
                if gains:
                    self._gain = min(max(float(np.median(gains)), 0.0), 2.0)

    def _delayed_far(self, far_block: np.ndarray) -> np.ndarray:
        """按 self.delay 从参考流里取与当前麦克风块对齐的参考块。"""
        self._far_buf = np.concatenate([self._far_buf, far_block])
        need = self.delay + self.B
        if len(self._far_buf) >= need:
            ref = self._far_buf[len(self._far_buf) - need:
                                len(self._far_buf) - self.delay]
        else:
            ref = np.zeros(self.B, dtype=np.float32)
        if len(self._far_buf) > self.sr:
            self._far_buf = self._far_buf[-self.sr:]
        return ref

    # ------------------------------------------------------------------
    def process(self, near_block, far_block=None):
        self._frames += 1
        near = np.asarray(near_block, dtype=np.float32).ravel()
        far = np.asarray(np.zeros(self.B, np.float32) if far_block is None
                         else far_block, dtype=np.float32).ravel()

        self._near_ring.append(near.copy())
        self._far_ring.append(far.copy())
        if self._frames % 2 == 0:
            self._estimate_delay()

        if self._last_delay != self.delay:
            self._last_delay = self.delay
            self._res_hist.clear()

        ref = self._delayed_far(far)
        echo = self._gain * ref
        e = near - echo

        near_pow = float(np.mean(near ** 2) + 1e-12)
        far_pow = float(np.mean(ref ** 2) + 1e-12)
        raw_pow = float(np.mean(e ** 2) + 1e-12)
        self._near_pow = 0.9 * self._near_pow + 0.1 * near_pow
        self._far_pow = 0.9 * self._far_pow + 0.1 * far_pow

        # 双讲检测：残差比最近残差低位明显抬高 → 用户开口（冻结增益）
        dtd = False
        if (self._delay_locked and self._frames > 80 and far_pow > 1e-6
                and len(self._res_hist) >= 20):
            base = float(np.percentile(self._res_hist, 20))
            dtd = base > 1e-9 and raw_pow > self.dtd_ratio * base
        self.dtd = dtd
        if dtd:
            self._dtd_freeze = 4
        elif self._dtd_freeze > 0:
            self._dtd_freeze -= 1

        # 增益估计：最小二乘 a = <near, ref> / <ref, ref>，仅在没有双讲时更新
        if self._delay_locked and self._dtd_freeze == 0 and far_pow > 1e-6:
            a = float(np.dot(near, ref) / (np.dot(ref, ref) + 1e-9))
            a = min(max(a, 0.0), 2.0)
            alpha = 0.2
            self._gain = (1 - alpha) * self._gain + alpha * a

        if far_pow > 1e-6 and not dtd:
            self._res_hist.append(raw_pow)

        if near_pow > 1e-6 and not dtd:
            inst = 10 * np.log10((near_pow + 1e-12) / (raw_pow + 1e-12))
            self.erle = 0.9 * self.erle + 0.1 * inst

        return e.astype(np.float32), True
