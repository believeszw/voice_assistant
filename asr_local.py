"""端侧双遍 ASR：流式 Paraformer（出中间结果/低延迟）+ 句尾 SenseVoice（整句校正）。

用法（一次发言 = 一次 start/feed.../finish）：
    asr = TwoPassASR()
    if asr.available():
        asr.start()
        for block in mic_blocks:            # 16k/16bit/mono bytes
            partial = asr.feed(block)       # 可显示的低延迟草稿
        final, engine = asr.finish(full_pcm)  # SenseVoice 校正后的最终文本

设计：
- 流式 Paraformer 负责边说边出字（partial），并作为云端不可用时的兜底；
- 句尾 SenseVoice 对整段音频重新识别，作为最终文本（精度更高，带标点）；
- 云端 MiMo ASR 仍是主力：assistant 优先用云端结果，云端失败才用本模块的 final。
"""

from pathlib import Path

import numpy as np

SR = 16000
MODEL_STREAM = "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
MODEL_SENSEVOICE = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"


class TwoPassASR:
    def __init__(self, models_dir=None, num_threads=2, log=print):
        self.log = log
        self.ok = False
        self.err = ""
        if models_dir:
            self.models_dir = Path(models_dir)
        else:
            self.models_dir = Path(__file__).resolve().parent / "models"
        self._stream_rec = None
        self._sv_rec = None
        self._stream = None
        self._partial = ""
        self._pcm = bytearray()
        import importlib.util

        if importlib.util.find_spec("sherpa_onnx") is None:  # pragma: no cover
            self.err = "sherpa_onnx 未安装"
            return
        try:
            self._init_stream()
            self._init_sensevoice()
            self.ok = True
        except Exception as e:  # pragma: no cover
            self.err = f"模型加载失败: {e}"
            self.log(f"[asr_local] {self.err}")

    # ---------- 初始化 ----------
    def _init_stream(self):
        import sherpa_onnx

        d = self.models_dir / MODEL_STREAM
        dec = d / "decoder.int8.onnx"
        if not dec.exists():
            dec = d / "decoder.onnx"
        for f in (d / "tokens.txt", d / "encoder.int8.onnx", dec):
            if not f.exists():
                raise FileNotFoundError(f)
        self._stream_rec = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=str(d / "tokens.txt"),
            encoder=str(d / "encoder.int8.onnx"),
            decoder=str(dec),
            num_threads=2,
            sample_rate=SR,
            feature_dim=80,
            decoding_method="greedy_search",
            enable_endpoint_detection=False,
            debug=False,
        )

    def _init_sensevoice(self):
        import sherpa_onnx

        d = self.models_dir / MODEL_SENSEVOICE
        model = d / "model.int8.onnx"
        if not model.exists():
            model = d / "model.onnx"
        for f in (model, d / "tokens.txt"):
            if not f.exists():
                raise FileNotFoundError(f)
        self._sv_rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model),
            tokens=str(d / "tokens.txt"),
            num_threads=2,
            use_itn=True,
            debug=False,
        )

    def available(self) -> bool:
        return self.ok

    # ---------- 一次发言 ----------
    def start(self):
        if not self.ok:
            return
        self._stream = self._stream_rec.create_stream()
        self._partial = ""
        self._pcm = bytearray()

    @staticmethod
    def _to_float(pcm_bytes) -> np.ndarray:
        return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    def feed(self, pcm_bytes: bytes) -> str:
        """喂一块音频，返回当前流式草稿（可能为"）。"""
        if not self.ok:
            return ""
        self._pcm.extend(pcm_bytes)
        samples = self._to_float(pcm_bytes)
        if samples.size == 0:
            return self._partial
        self._stream.accept_waveform(SR, samples)
        rec = self._stream_rec
        while rec.is_ready(self._stream):
            rec.decode_stream(self._stream)
        text = rec.get_result(self._stream)
        if text:
            self._partial = text
        return self._partial

    def finish(self, pcm_bytes: bytes = b"") -> tuple[str, str]:
        """结束一次发言，返回 (最终文本, 引擎标签)。

        SenseVoice 在整段音频上重新识别；若失败则退回流式结果。
        """
        if not self.ok:
            return "", "unavailable"
        # feed() 已经把每块音频累积进 _pcm；只有从未 feed 过时才用传入的整段音频，
        # 避免把同一段音频算两遍。
        if pcm_bytes and not self._pcm:
            self._pcm.extend(pcm_bytes)
        pcm = bytes(self._pcm)
        stream_text, sence_text = "", ""
        # 1) 流式收尾（补静音 flush）
        try:
            if self._stream is not None:
                self._stream.accept_waveform(SR, np.zeros(SR // 2, dtype=np.float32))
                self._stream.input_finished()
                rec = self._stream_rec
                while rec.is_ready(self._stream):
                    rec.decode_stream(self._stream)
                stream_text = rec.get_result(self._stream) or self._partial
        except Exception as e:  # pragma: no cover
            self.log(f"[asr_local] 流式收尾失败: {e}")
        # 2) SenseVoice 整句校正
        try:
            if pcm:
                samples = self._to_float(pcm)
                st = self._sv_rec.create_stream()
                st.accept_waveform(SR, samples)
                self._sv_rec.decode_stream(st)
                sence_text = (st.result.text or "").strip()
        except Exception as e:  # pragma: no cover
            self.log(f"[asr_local] SenseVoice 失败: {e}")
        final, engine = self._choose(sence_text, stream_text)
        return final, engine

    @staticmethod
    def _clean(text: str) -> str:
        import re

        return re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", text or "")

    @classmethod
    def _choose(cls, sv: str, stream: str) -> tuple[str, str]:
        """在 SenseVoice 整句结果和流式结果之间选一个。

        SenseVoice 带标点/ITN，通常更准；但它在很弱的音频上会「脑补」出英文短词
        （例如 Yeah.），或只吐出半句话。这两类情况退回流式结果更稳。
        """
        sv_c, st_c = cls._clean(sv), cls._clean(stream)
        if not sv_c:
            return (stream, "paraformer-stream") if st_c else ("", "none")
        if not st_c:
            return sv, "sensevoice"

        def _cjk(s: str) -> int:
            return sum("\u4e00" <= ch <= "\u9fff" for ch in s)

        cjk = _cjk
        # 1) 整句结果没有任何中文、流式有：多半是脑补
        if cjk(sv_c) == 0 and cjk(st_c) >= 2:
            return stream, "paraformer-stream"
        # 2) 整句结果明显比流式短（只听到半句）：用流式补全
        if len(sv_c) < 0.5 * len(st_c) and len(st_c) >= 2:
            return stream, "paraformer-stream"
        return sv, "sensevoice"
