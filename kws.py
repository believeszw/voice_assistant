"""本地唤醒词检测（sherpa-onnx keyword spotter）。

相比用通用识别模型匹配「小助手」三个字，专用 KWS 模型：
- 只认注册过的关键词（`kws_keywords.txt`），不会把任意近音词当成唤醒；
- 3.3M 参数、int8 量化，CPU 单核即可实时；
- 输出带起点，可以用来算唤醒延迟。

用法：
    kws = WakeWord(log=print)
    if kws.available():
        kw = kws.feed(pcm_16k_int16_bytes)   # 返回命中关键词或 None
"""

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = ROOT / "models" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01-mobile"
DEFAULT_KEYWORDS = ROOT / "kws_keywords.txt"
SR = 16000


class WakeWord:
    def __init__(self, model_dir=None, keywords_file=None, threshold=0.25,
                 score=1.0, num_threads=2, log=print):
        self.ok = False
        self.err = ""
        self.log = log
        self._kws = None
        self._stream = None
        try:
            import sherpa_onnx

            d = Path(model_dir or DEFAULT_MODEL_DIR)
            onnx = {p.name: p for p in d.glob("*.onnx")}

            def pick(prefix: str):
                """优先 int8 量化版；没有就退 fp32（decoder 通常没有 int8 版）。"""
                cands = sorted((n, p) for n, p in onnx.items() if n.startswith(prefix))
                for n, p in cands:
                    if "int8" in n:
                        return str(p)
                return str(cands[0][1]) if cands else None

            encoder, decoder, joiner = pick("encoder"), pick("decoder"), pick("joiner")
            tokens = d / "tokens.txt"
            keywords = Path(keywords_file or DEFAULT_KEYWORDS)
            if not all([encoder, decoder, joiner]) or not tokens.exists():
                raise FileNotFoundError(f"模型文件不完整: {d}")
            if not keywords.exists():
                raise FileNotFoundError(f"关键词文件不存在: {keywords}")
            self._kws = sherpa_onnx.KeywordSpotter(
                tokens=str(tokens),
                encoder=encoder,
                decoder=decoder,
                joiner=joiner,
                keywords_file=str(keywords),
                num_threads=num_threads,
                keywords_score=score,
                keywords_threshold=threshold,
                provider="cpu",
            )
            self._stream = self._kws.create_stream()
            self.ok = True
        except Exception as exc:  # noqa: BLE001
            self.err = f"{type(exc).__name__}: {exc}"

    def available(self) -> bool:
        return self.ok

    def reset(self):
        if self.ok:
            self._kws.reset_stream(self._stream)

    def feed(self, pcm: bytes):
        """喂一段 16k/单声道/int16 PCM，命中唤醒词返回关键词文本，否则 None。"""
        if not self.ok or not pcm:
            return None
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self._stream.accept_waveform(SR, samples)
        hit = None
        while self._kws.is_ready(self._stream):
            self._kws.decode_stream(self._stream)
            text = self._kws.get_result(self._stream)
            if text:
                hit = text
                self._kws.reset_stream(self._stream)
                break
        return hit
