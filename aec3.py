"""WebRTC AEC3 绑定（webrtc-audio-processing v2.1，C ABI 包装 DLL）。

构建产物在 tools/aec3/：
- aec3_wrap.dll                  —— 本文件的 C 包装（AEC3 + NS）
- webrtc-audio-processing-2-1.dll —— 上游库

对外接口与 aec_nlms.AEC 兼容：
    aec = AEC3()
    out, ok = aec.process(near_frame, far_frame)   # 10ms 帧（160 样本 @16k）
    aec.erle / aec.delay / aec.dtd / aec.frame

AEC3 自带延迟估计与双讲检测，不需要外部对齐；这里只暴露 10ms 帧尺寸，
让 frontend 按 160 样本分块，保证输入输出严格等长、无补零。
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

import numpy as np

FRAME10 = 160  # 10 ms @ 16 kHz


def _dll_dir() -> Path:
    base = Path(__file__).resolve().parent
    cands = [
        base / "tools" / "aec3",
        base / "aec3",
        Path(__file__).with_name("aec3"),
    ]
    for p in cands:
        if (p / "aec3_wrap.dll").exists():
            return p
    return cands[0]


class AEC3:
    """AEC3 包装：process(near, far) -> (clean, True)。"""

    def __init__(self, sr: int = 16000, frame: int = FRAME10,
                 dll_dir: str = ""):
        self.sr = int(sr)
        self.frame = int(frame)
        self.delay = 0
        self.dtd = False
        self.erle = 0.0
        self._erle_ema = None
        d = Path(dll_dir) if dll_dir else _dll_dir()
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(d))
        self._lib = ctypes.CDLL(str(d / "aec3_wrap.dll"))
        self._lib.wap_create.restype = ctypes.c_void_p
        self._lib.wap_create.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.wap_process_far.argtypes = [ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_int16)]
        self._lib.wap_process_near.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int16),
            ctypes.POINTER(ctypes.c_int16)]
        self._lib.wap_set_stream_delay.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._lib.wap_destroy.argtypes = [ctypes.c_void_p]
        self._h = self._lib.wap_create(self.sr, 1)
        if not self._h:
            raise RuntimeError("wap_create failed")
        if frame != FRAME10:
            raise ValueError(f"AEC3 只支持 10ms 帧（{FRAME10} 样本），收到 {frame}")

    # ------------------------------------------------------------------
    def process(self, near: np.ndarray, far: np.ndarray | None = None):
        near = np.asarray(near, dtype=np.float32)
        if near.size != self.frame:
            raise ValueError(f"expect {self.frame} samples, got {near.size}")
        n = np.clip(near * 32768.0, -32768, 32767).astype(np.int16)
        if far is None:
            f = np.zeros(self.frame, dtype=np.int16)
        else:
            far = np.asarray(far, dtype=np.float32)
            if far.size < self.frame:
                far = np.pad(far, (0, self.frame - far.size))
            f = np.clip(far[: self.frame] * 32768.0, -32768, 32767).astype(np.int16)
        y = np.zeros(self.frame, dtype=np.int16)
        fp = f.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
        np_ = n.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
        yp = y.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
        self._lib.wap_process_far(self._h, fp)
        rc = self._lib.wap_process_near(self._h, np_, yp)
        out = y.astype(np.float32) / 32768.0
        if rc != 0:
            out = near
        # ERLE 估计（噪声门限内才更新，避免静音段把 EMA 拉飞）
        near_pow = float(np.mean(near.astype(np.float64) ** 2)) + 1e-12
        out_pow = float(np.mean(out.astype(np.float64) ** 2)) + 1e-12
        if near_pow > 1e-6:
            cur = 10.0 * np.log10(near_pow / out_pow)
            cur = float(np.clip(cur, -40.0, 60.0))
            self._erle_ema = cur if self._erle_ema is None else 0.9 * self._erle_ema + 0.1 * cur
            self.erle = self._erle_ema
        return out, True

    def close(self):
        if getattr(self, "_h", None):
            self._lib.wap_destroy(self._h)
            self._h = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
