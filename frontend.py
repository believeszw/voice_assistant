"""音频前端：回声抑制（AEC）+ 语音活动检测（Silero VAD）。

全双工语音助手在「自己的播报声」还没停的时候也要听麦克风：
- TTS 播放的 PCM 作为参考信号（far-end），从麦克风信号里减掉自己的声音；
- 剩下的信号过 Silero VAD，判断用户是不是在说话，用于打断（barge-in）。

AEC 默认用 WebRTC AEC3（tools/aec3 下的 webrtc-audio-processing v2.1 C ABI
包装，延迟估计/双讲检测由库内做）；DLL 不可用时自动退回自研 FLMS
（aec_nlms.py，参考对齐 + 最小二乘增益）。切换见 config.AEC_ENGINE。

接口
----
frontend = AudioFrontend()
frontend.push_far(pcm_far)                       # 播放 TTS 时喂参考信号
clean, prob, speech = frontend.process(pcm_near) # 麦克风 -> 去回声 + VAD
if frontend.barge_in: ...                        # 用户打断
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np

from aec_nlms import AEC as _FlmsAEC

try:  # WebRTC AEC3（tools/aec3 下的 C ABI 包装 DLL）；没有就退回自研 FLMS
    from aec3 import AEC3 as _AEC3
except Exception:  # pragma: no cover
    _AEC3 = None


def _make_aec():
    """按 config.AEC_ENGINE 选择 AEC：auto 优先 AEC3，失败退回 FLMS。"""
    try:
        import config as _cfg
        engine = str(getattr(_cfg, "AEC_ENGINE", "auto")).lower()
    except Exception:
        engine = "auto"
    if _AEC3 is not None and engine in ("auto", "aec3"):
        try:
            return _AEC3()
        except Exception:
            if engine == "aec3":
                raise
    return _FlmsAEC()


try:  # onnxruntime 是软依赖：没有就用能量 VAD 兜底
    import onnxruntime as ort
except Exception:  # pragma: no cover
    ort = None

SR = 16000
FRAME = 256          # AEC 帧长 16ms
VAD_SR = 8000        # 本机 silero_vad.onnx 只有 8k 采样率下判据正常
VAD_WIN = 256        # 8k 下 32ms

MODEL_CANDIDATES = (
    Path(__file__).with_name("models") / "silero" / "silero_vad.onnx",
    Path(__file__).with_name("models") / "silero_vad.onnx",
)


def _to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def _to_bytes(x: np.ndarray) -> bytes:
    return np.clip(x * 32768.0, -32768, 32767).astype(np.int16).tobytes()


class SileroVAD:
    """Silero VAD（ONNX）：8k 域、256 样本一帧。"""

    def __init__(self, model_path: str = "", threshold: float = 0.35,
                 hangover_ms: int = 300, min_speech_ms: int = 96,
                 sr: int = VAD_SR):
        self.sr = sr
        self.threshold = threshold
        self.hangover = max(1, int(hangover_ms / (1000 * VAD_WIN / sr)))
        self.min_speech = max(1, int(min_speech_ms / (1000 * VAD_WIN / sr)))
        self._buf = np.zeros(0, dtype=np.float32)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._prob = 0.0
        self._active = False
        self._on = 0
        self._silence = 0
        self._session = None
        self._use_onnx = False
        path = Path(model_path) if model_path else next(
            (p for p in MODEL_CANDIDATES if p.exists()), None)
        if ort is not None and path is not None:
            self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            self._use_onnx = True
        self._floor = 0.005

    def reset(self):
        self._buf = np.zeros(0, dtype=np.float32)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._prob = 0.0
        self._active = False
        self._on = 0
        self._silence = 0

    def _infer(self, block: np.ndarray) -> float:
        if not self._use_onnx:
            rms = float(np.sqrt(np.mean(block ** 2) + 1e-12))
            self._floor = 0.9 * self._floor + 0.1 * rms
            return 1.0 if rms > max(0.01, 3.0 * self._floor) else 0.0
        x = block.reshape(1, -1).astype(np.float32)
        sr = np.array(self.sr, dtype=np.int64)
        out, self._state = self._session.run(None, {"input": x, "state": self._state, "sr": sr})
        return float(np.asarray(out).reshape(-1)[0])

    def process(self, samples: np.ndarray):
        self._buf = np.concatenate([self._buf, np.asarray(samples, dtype=np.float32)])
        probs = []
        while len(self._buf) >= VAD_WIN:
            block = self._buf[:VAD_WIN]
            self._buf = self._buf[VAD_WIN:]
            p = self._infer(block)
            probs.append(p)
            self._prob = p
            if p >= self.threshold:
                self._on += 1
                self._silence = 0
            else:
                self._silence += 1
                if self._silence >= self.hangover:
                    self._on = 0
            self._active = self._on >= self.min_speech
        # 一次调用可能含多帧(256 样本/帧)，只返回最后一帧会让打断判定剧烈抖动；
        # 返回本块内的最大概率，代表「这块里到底有没有人声」。
        out_prob = max(probs) if probs else self._prob
        return out_prob, self._active


class AudioFrontend:
    """AEC + VAD；播放期间判断用户是否打断。"""

    def __init__(self, vad: SileroVAD = None, aec_enabled: bool = True):
        self.aec = _make_aec() if aec_enabled else None
        self.frame = int(getattr(self.aec, "frame", FRAME))
        self.vad = vad or SileroVAD()
        try:
            import config as _cfg
            ns_on = bool(getattr(_cfg, "NS_ENABLED", True))
            agc_on = bool(getattr(_cfg, "AGC_ENABLED", True))
            agc_target = float(getattr(_cfg, "AGC_TARGET_RMS", 0.05))
        except Exception:  # 单独跑 frontend 时没有 config 也能工作
            ns_on, agc_on, agc_target = True, True, 0.05
        # 唤醒链路用语音保护档：避免过减削掉 0 dB 唤醒词
        self.ns = (NoiseSuppressor(speech_floor=0.35, speech_start=1.6,
                                   speech_ratio=2.6) if ns_on else None)
        self.agc = AGC(target_rms=agc_target) if agc_on else None
        self.last_enhanced = np.zeros(0, dtype=np.float32)
        self._far_acc = np.zeros(0, dtype=np.float32)
        self._near_acc = np.zeros(0, dtype=np.float32)
        self.last_prob = 0.0
        self.speaking = False
        self.last_erle = 0.0
        self.last_dtd = False
        self.barge_in = False
        self._clean_hist = deque(maxlen=200)
        self._prob_hist = deque(maxlen=6)
        self._barge_hits = 0
        self._prob_hits = 0
        # 打断预录：保存最近 3 秒原始麦克风音频，打断瞬间可回捞开头
        self.sr = getattr(self.aec, "sr", 16000)
        self._near_raw = np.zeros(0, dtype=np.float32)
        self._clean_ring = np.zeros(0, dtype=np.float32)
        self.barge_evidence = ""
        self.barge_ms = 0

    def reset(self):
        self.vad.reset()
        if self.aec:
            self.aec = _make_aec()
            self.frame = int(getattr(self.aec, "frame", FRAME))
        if self.ns is not None:
            self.ns.reset()
        if self.agc is not None:
            self.agc.reset()
        self._far_acc = np.zeros(0, dtype=np.float32)
        self._near_acc = np.zeros(0, dtype=np.float32)
        self._near_raw = np.zeros(0, dtype=np.float32)
        self._clean_ring = np.zeros(0, dtype=np.float32)
        self.speaking = False
        self.barge_in = False
        self.barge_evidence = ""
        self._barge_hits = 0
        self._prob_hits = 0
        self._prob_hist.clear()

    def recent_near(self, seconds: float = 0.7) -> bytes:
        """最近 N 秒的原始麦克风 PCM（int16），用于打断后补回开头。"""
        if self._near_raw.size == 0:
            return b""
        n = int(self.sr * max(0.05, seconds))
        seg = self._near_raw[-n:]
        return _to_bytes(seg)

    def recent_clean(self, seconds: float = 0.7) -> bytes:
        """最近 N 秒去回声后的 PCM（int16）：打断预录用，避免把播报声录进去。"""
        if self._clean_ring.size == 0:
            return b""
        n = int(self.sr * max(0.05, seconds))
        seg = self._clean_ring[-n:]
        return _to_bytes(seg)

    def push_far(self, pcm: bytes):
        """播放 TTS 时把参考 PCM 推入队列（块大小任意）。"""
        if pcm:
            self._far_acc = np.concatenate([self._far_acc, _to_float(pcm)])

    def process(self, near_pcm: bytes, enhanced: bool = False):
        """麦克风一块（任意长度）→ (去回声后的 PCM, VAD 概率, 是否在说话)。

        enhanced=True 时返回再经过降噪 + 自动增益的信号（唤醒/识别用）；
        打断判定始终基于 AEC 输出，避免增益改变阈值口径。
        """
        near = _to_float(near_pcm)
        if near.size:
            self._near_raw = np.concatenate([self._near_raw, near])
            cap = self.sr * 3
            if self._near_raw.size > cap:
                self._near_raw = self._near_raw[-cap:]
        self._near_acc = np.concatenate([self._near_acc, near])
        clean_chunks = []
        while len(self._near_acc) >= self.frame:
            frame = self._near_acc[:self.frame]
            self._near_acc = self._near_acc[self.frame:]
            if self.aec:
                fsz = self.frame
                if len(self._far_acc) >= fsz:
                    far = self._far_acc[:fsz]
                    self._far_acc = self._far_acc[fsz:]
                else:
                    far = np.zeros(fsz, dtype=np.float32)
                out, _ = self.aec.process(frame, far)
                self.last_erle = self.aec.erle
            else:
                out = frame
            clean_chunks.append(out)
        if not clean_chunks:
            return b"", self.vad._prob, self.vad._active

        clean = np.concatenate(clean_chunks)
        self._clean_ring = np.concatenate([self._clean_ring, clean])
        cap = self.sr * 3
        if self._clean_ring.size > cap:
            self._clean_ring = self._clean_ring[-cap:]
        enh = self._enhance(clean) if enhanced else clean
        # VAD 用 8k：两两平均降采样（用去回声信号，保持既有阈值口径）
        even = len(clean) - (len(clean) % 2)
        vad_in = (clean[0:even:2] + clean[1:even:2]) / 2.0
        prob, active = self.vad.process(vad_in)
        self.last_prob = prob
        self.speaking = active
        self.last_dtd = self.aec.dtd if self.aec else True

        # 打断判定：三路证据融合——能量比（相对底噪/漏音基线）、绝对能量、VAD 概率。
        # 真实设备上回声很弱、AEC 压不出 ERLE 时，单用绝对能量阈值会漏检正常音量，
        # 所以以「相对基线」为主证据，再让 VAD 概率做二次确认。
        rms = float(np.sqrt(np.mean(clean ** 2) + 1e-12))
        self._clean_hist.append(rms)
        if len(self._clean_hist) < 10:  # 前 ~0.5s 基线未建立（按 50ms 块计），避免起播瞬态误判
            self.barge_in = False
            self.barge_evidence = ""
            return _to_bytes(enh), prob, active
        base = max(0.003, float(np.percentile(self._clean_hist, 25)))
        ratio = min(rms / (base + 1e-9), 99.0)
        self._erle_peak = max(getattr(self, "_erle_peak", 0.0), self.last_erle)
        weak_echo = self._erle_peak <= 6.0
        # 真实播报漏音在本机能到 rms 0.02~0.03，所以能量门槛必须高于漏音，
        # 否则「播报自己」就会被当成用户打断。
        self._prob_hist.append(prob)
        prob_peak = max(self._prob_hist)
        # 能量类证据不再强制要求 VAD 峰值：真人小声说话时 AEC 后能量很高，
        # 但 VAD 可能还没站稳；误判交给 assistant 的「暂停→确认」阶段兜底。
        ratio_ev = ratio > 8.0 and rms > 0.04
        loud_ev = rms > 0.10
        strong_ev = ratio > 20.0 and rms > 0.05
        prob_ev = prob >= 0.6 and rms > 0.04
        self._barge_hits = self._barge_hits + 1 if (ratio_ev or loud_ev) else 0
        self._prob_hits = self._prob_hits + 1 if prob_ev else 0
        self.barge_in = bool(
            self._barge_hits >= 2
            or strong_ev
            or (prob >= 0.9 and rms > 0.05)
            or (self._prob_hits >= 2 and rms > 0.04))
        self.barge_evidence = (
            f"rms={rms:.3f} ratio={ratio:.1f} base={base:.3f} prob={prob:.2f} "
            f"pk={prob_peak:.2f} weak={int(weak_echo)} hits={self._barge_hits}/{self._prob_hits}")
        return _to_bytes(enh), prob, active

    def _enhance(self, clean: np.ndarray) -> np.ndarray:
        """去回声之后的降噪（唤醒链路）。

        AEC 之后仍有底噪（风扇/空调/主机），会拉低唤醒率；谱减把稳态噪声压下去。
        这里不做 AGC：KWS 模型对电平本身不敏感，放大底噪反而会增加误唤醒；
        AGC 只在 ASR 前处理里用（enhance_pcm）。
        """
        x = clean
        if self.ns is not None:
            x = self.ns.process(x)
        self.last_enhanced = x
        return x


class NoiseSuppressor:
    """过减谱减降噪（oversubtraction + 增益平滑）。

    只针对稳态噪声（风扇、空调、机箱底噪）；对突发噪声/混响无能为力。
    无第三方依赖的工程实现，量产应换 DeepFilterNet / RNNoise。
    """

    N = 256       # 16 ms 帧（16 kHz）
    HOP = 128     # 50% 重叠

    def __init__(self, oversub: float = 3.4, floor_gain: float = 0.03,
                 smooth: float = 0.6, speech_floor: float | None = None,
                 speech_ratio: float = 2.6, speech_start: float = 1.6):
        self.w = np.hanning(self.N).astype(np.float32)
        self.oversub = float(oversub)
        self.floor_gain = float(floor_gain)
        self.smooth = float(smooth)
        # 语音保护档：speech_floor > floor_gain 时抬高语音帧增益下限，
        # 用于唤醒链路（KWS 对过减敏感）；ASR 前处理用深降噪档（speech_floor=None）。
        self.speech_floor = float(floor_gain if speech_floor is None else speech_floor)
        self.speech_ratio = float(speech_ratio)
        self.speech_start = float(speech_start)
        self.reset()

    def reset(self):
        self._in = np.zeros(0, dtype=np.float32)
        self._ola = np.zeros(self.N, dtype=np.float32)
        # 50% 重叠的固有延迟（128 样本 ≈ 8 ms），先补零保证输出与输入等长
        self._ready = np.zeros(self.N - self.HOP, dtype=np.float32)
        self._noise = None
        self._gain = np.ones(self.N // 2 + 1, dtype=np.float32)
        self._snr_ratio = 1.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        x = np.asarray(samples, dtype=np.float32)
        n_out = len(x)
        self._in = np.concatenate([self._in, x])
        while len(self._in) >= self.N:
            seg = self._in[:self.N]
            self._in = self._in[self.HOP:]
            X = np.fft.rfft(seg * self.w)
            P = (X.real ** 2 + X.imag ** 2) + 1e-10
            if self._noise is None:
                self._noise = P.copy()
            else:
                # 噪声估计：像噪声的帧快跟（0.10），像语音的帧慢跟（0.002）
                ratio = P / (self._noise + 1e-12)
                upd = np.where(ratio < 2.0, 0.10, 0.002).astype(np.float32)
                self._noise = (1.0 - upd) * self._noise + upd * P
            # 帧级信噪比（平滑）：明显噪声帧 → 深降噪；明显语音帧 → 保护
            tot = float(np.sum(P)) + 1e-12
            ntot = float(np.sum(self._noise)) + 1e-12
            r = tot / ntot
            self._snr_ratio = 0.8 * self._snr_ratio + 0.2 * r
            if self._snr_ratio < 1.15:
                floor = 0.01
            elif self._snr_ratio < self.speech_start:
                floor = self.floor_gain
            else:
                lift = np.clip((self._snr_ratio - self.speech_start) /
                               (self.speech_ratio - self.speech_start), 0.0, 1.0)
                floor = self.floor_gain + (self.speech_floor - self.floor_gain) * lift
            g = 1.0 - self.oversub * self._noise / (P + 1e-12)
            g = np.clip(g, floor, 1.0).astype(np.float32)
            self._gain = self.smooth * self._gain + (1.0 - self.smooth) * g
            y = np.fft.irfft(X * self._gain, n=self.N).astype(np.float32) * self.w
            self._ola += y
            self._ready = np.concatenate([self._ready, self._ola[:self.HOP]])
            self._ola = np.concatenate(
                [self._ola[self.HOP:], np.zeros(self.HOP, dtype=np.float32)])
        if len(self._ready) >= n_out:
            out = self._ready[:n_out]
            self._ready = self._ready[n_out:]
        else:
            out = np.zeros(n_out, dtype=np.float32)
            self._ready = np.zeros(0, dtype=np.float32)
        # hann 窗 + 50% 重叠：平方窗之和约 0.75
        return (out / 0.75).astype(np.float32)


class AGC:
    """自动增益：把语音拉到目标 RMS；压得快、放得慢，末端软限幅。"""

    def __init__(self, target_rms: float = 0.05, min_gain: float = 0.5,
                 max_gain: float = 16.0):
        self.target_rms = float(target_rms)
        self.min_gain = float(min_gain)
        self.max_gain = float(max_gain)
        self._gain = 1.0

    def reset(self):
        self._gain = 1.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return x
        rms = float(np.sqrt(np.mean(x ** 2) + 1e-12))
        desired = float(np.clip(self.target_rms / rms, self.min_gain, self.max_gain))
        if desired < self._gain:
            self._gain = 0.5 * self._gain + 0.5 * desired      # 太响：快速压回来
        else:
            self._gain = 0.75 * self._gain + 0.25 * desired     # 太轻：放开（不无限放大底噪）
        y = x * self._gain
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak > 0.98:
            y = y * (0.98 / peak)
        return y.astype(np.float32)


def enhance_pcm(pcm: bytes) -> bytes:
    """整段音频离线降噪 + 自动增益（ASR 前处理用）。"""
    if not pcm:
        return b""
    x = _to_float(pcm)
    ns = NoiseSuppressor()
    agc = AGC()
    out = np.zeros_like(x)
    step = 512
    for i in range(0, len(x), step):
        seg = x[i:i + step]
        out[i:i + len(seg)] = agc.process(ns.process(seg))
    return _to_bytes(out)
