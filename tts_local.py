"""端侧 TTS 双路后端：Piper（首选，低延迟）→ sherpa-onnx VITS（兜底）。

定位（选型 §5 降级链）：云端 TTS 不可用或超时 > TTS_CLOUD_TIMEOUT 时立刻改用端侧合成，
保证隧道、地库、断网场景仍能播报；同时给 AEC 提供播放参考信号（复用 tts._play_wav）。

后端选择：
1. Piper（models/tts/piper-zh_CN-huayan-medium/zh_CN-huayan-medium.onnx）
   - 选型文档 §4 指定的端侧 TTS；VITS 声学模型 + espeak-ng 音素，22050 Hz，63 MB；
   - ONNX Runtime CPU 推理，实测 RTF≈0.1，支持流式分块（voice.synthesize 是生成器）；
   - 依赖：pip install piper-tts（wheel 自带 espeak-ng 数据，无需额外系统库）。
2. sherpa-onnx VITS MeloTTS（models/tts/vits-melo-tts-zh_en/model.int8.onnx）
   - Piper 缺失时的兜底；复用项目已有 sherpa-onnx 运行时，44.1 kHz、音质更好但慢（RTF≈1.2）。
   - 获取：tools/_fetch_tts.py。

对外接口（tts.py 只依赖这几个）：
    available() -> bool            后端模型是否就绪（不加载）
    backend_name() -> str          当前后端名（用于日志/README）
    error() -> str                 加载失败原因
    sample_rate() -> int           当前后端输出采样率
    synth_wav(text, speed=None) -> bytes   整句合成 → 16bit 单声道 wav
    stream(text, speed=None) -> Iterator[bytes]  分块 PCM（int16，小端），供低延迟边播
    last_stats() -> dict           最近一次合成的耗时统计
    warmup() -> bool               预热（加载模型 + 一次短句）
"""

import threading
import time
import wave
from io import BytesIO
from pathlib import Path

import numpy as np

import config

try:  # Piper 首选后端
    from piper import PiperVoice, SynthesisConfig

    _HAS_PIPER = True
except Exception:  # pragma: no cover
    PiperVoice = None
    SynthesisConfig = None
    _HAS_PIPER = False

try:  # sherpa-onnx 兜底后端
    import sherpa_onnx

    _HAS_SHERPA = True
except Exception:  # pragma: no cover
    _HAS_SHERPA = False

_PIPER_DIR = Path(config.TTS_LOCAL_DIR).parent / "piper-zh_CN-huayan-medium"
_RULE_FSTS = ("date.fst", "number.fst", "phone.fst", "new_heteronym.fst")

_VOICE = None          # PiperVoice
_TTS = None            # sherpa OfflineTts
_LOCK = threading.Lock()
_ERR = ""
_BACKEND = ""
_LOAD_MS = 0.0
_SR = 16000
_LAST = {"backend": "", "synth_ms": 0.0, "first_chunk_ms": 0.0,
         "audio_seconds": 0.0, "text_len": 0, "backend_load_ms": 0.0, "error": ""}


# ---------------------------------------------------------------- 文件与加载

def _piper_model() -> Path | None:
    if not _PIPER_DIR.is_dir():
        return None
    for p in _PIPER_DIR.glob("*.onnx"):
        if p.is_file():
            return p
    return None


def _sherpa_model() -> Path | None:
    d = Path(config.TTS_LOCAL_DIR)
    for name in ("model.int8.onnx", "model.onnx"):
        p = d / name
        if p.exists():
            return p
    return None


def available() -> bool:
    """端侧 TTS 是否可用（只看文件，不加载模型）。"""
    return bool(_piper_model() or _sherpa_model())


def backend_name() -> str:
    return _BACKEND


def sample_rate() -> int:
    return _SR


def error() -> str:
    if not _BACKEND and not _ERR:
        _load()
    return _ERR


def _load():
    """按 Piper → sherpa 顺序加载，返回 (backend, obj)。"""
    global _VOICE, _TTS, _ERR, _BACKEND, _LOAD_MS, _SR
    if _BACKEND:
        return _BACKEND, (_VOICE or _TTS)
    with _LOCK:
        if _BACKEND:
            return _BACKEND, (_VOICE or _TTS)
        t0 = time.time()

        prefer = (getattr(config, "TTS_LOCAL_BACKEND", "") or "").lower()
        model = _piper_model() if prefer in ("", "piper") else None
        if model is not None and _HAS_PIPER:
            try:
                voice = PiperVoice.load(str(model))
                sr = int(getattr(voice.config, "sample_rate", 0) or 0)
                if sr <= 0:
                    sr = 22050
                _VOICE = voice
                _SR = sr
                _BACKEND = model.stem
                _LOAD_MS = (time.time() - t0) * 1000.0
                print(f"[TTS] 端侧模型已加载（{_LOAD_MS / 1000:.2f}s，Piper {_BACKEND} {_SR}Hz）")
                return _BACKEND, _VOICE
            except Exception as exc:  # pragma: no cover
                print(f"[TTS] Piper 加载失败，改用 sherpa：{type(exc).__name__}: {str(exc)[:120]}")

        model = _sherpa_model()
        if model is not None and _HAS_SHERPA:
            d = model.parent
            rule_fsts = ",".join(str(d / f) for f in _RULE_FSTS if (d / f).exists())
            vits_kwargs = dict(model=str(model), tokens=str(d / "tokens.txt"))
            if (d / "lexicon.txt").exists():
                vits_kwargs["lexicon"] = str(d / "lexicon.txt")
            dict_dir = d / "dict"
            if dict_dir.is_dir() and any(dict_dir.iterdir()):
                vits_kwargs["dict_dir"] = str(dict_dir)
            try:
                _TTS = sherpa_onnx.OfflineTts(
                    sherpa_onnx.OfflineTtsConfig(
                        model=sherpa_onnx.OfflineTtsModelConfig(
                            vits=sherpa_onnx.OfflineTtsVitsModelConfig(**vits_kwargs),
                            num_threads=config.TTS_LOCAL_THREADS,
                            debug=False,
                            provider="cpu",
                        ),
                        rule_fsts=rule_fsts,
                        max_num_sentences=1,
                    )
                )
                _SR = int(_TTS.sample_rate or 16000)
                _BACKEND = "vits-melo-tts-zh_en"
                _LOAD_MS = (time.time() - t0) * 1000.0
                print(f"[TTS] 端侧模型已加载（{_LOAD_MS / 1000:.2f}s，sherpa {_BACKEND} {_SR}Hz）")
                return _BACKEND, _TTS
            except Exception as exc:  # pragma: no cover
                _ERR = f"sherpa 加载失败 {type(exc).__name__}: {str(exc)[:160]}"

        if not available():
            _ERR = f"端侧 TTS 模型缺失：{_PIPER_DIR} / {config.TTS_LOCAL_DIR}"
        elif not _HAS_PIPER and not _HAS_SHERPA:
            _ERR = "piper-tts 与 sherpa-onnx 均不可用"
        if _ERR:
            print("[TTS] 端侧模型加载失败:", _ERR)
        return "", None


# ---------------------------------------------------------------- 合成

def _piper_pcm(text: str, speed: float):
    """逐块产出 (int16 np.ndarray)，同时返回首块耗时。"""
    cfg = SynthesisConfig(length_scale=1.0 / max(0.5, min(2.0, speed)))
    t0 = time.time()
    first = 0.0
    for chunk in _VOICE.synthesize(text, syn_config=cfg):
        pcm = getattr(chunk, "audio_int16_array", None)
        if pcm is None:
            pcm = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
        if first == 0.0:
            first = (time.time() - t0) * 1000.0
            _LAST["first_chunk_ms"] = first
        yield np.asarray(pcm, dtype=np.int16)


def synth_wav(text: str, speed: float = None) -> bytes:
    """端侧合成 → 16bit 单声道 wav 字节。失败返回 b""。"""
    text = (text or "").strip()
    if not text:
        return b""
    back, obj = _load()
    if not back or obj is None:
        return b""
    speed = config.TTS_LOCAL_SPEED if speed is None else speed
    t0 = time.time()
    try:
        if _VOICE is not None:
            pcm = b"".join(c.tobytes() for c in _piper_pcm(text, speed))
            sr = _SR
        else:
            audio = _TTS.generate(text, sid=0, speed=speed)
            samples = np.asarray(audio.samples, dtype=np.float32)
            pcm = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16).tobytes()
            sr = int(audio.sample_rate or _SR)
        if not pcm:
            return b""
        buf = BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm)
        _LAST.update(backend=_BACKEND, synth_ms=(time.time() - t0) * 1000.0,
                     audio_seconds=len(pcm) / 2.0 / sr, text_len=len(text),
                     backend_load_ms=_LOAD_MS, error="")
        return buf.getvalue()
    except Exception as exc:  # pragma: no cover
        _LAST.update(backend=_BACKEND, error=f"{type(exc).__name__}: {str(exc)[:120]}")
        print("[TTS] 端侧合成失败:", _LAST["error"])
        return b""


def stream(text: str, speed: float = None):
    """流式合成：逐块产出 int16 PCM（小端）。Piper 真流式；sherpa 退化为整句一块。"""
    text = (text or "").strip()
    if not text:
        return
    back, obj = _load()
    if not back or obj is None:
        return
    speed = config.TTS_LOCAL_SPEED if speed is None else speed
    t0 = time.time()
    if _VOICE is not None:
        for pcm in _piper_pcm(text, speed):
            _LAST.update(backend=_BACKEND, synth_ms=(time.time() - t0) * 1000.0,
                         audio_seconds=0.0, text_len=len(text), backend_load_ms=_LOAD_MS, error="")
            yield pcm.tobytes()
        _LAST["synth_ms"] = (time.time() - t0) * 1000.0
        return
    data = synth_wav(text, speed)
    if data:
        yield data[44:]  # 跳过 wav 头（标准 44 字节）


def last_stats() -> dict:
    return dict(_LAST)


def warmup() -> bool:
    """预热：加载模型 + 一次短句合成（避免首次播报卡顿）。"""
    if not available():
        return False
    back, obj = _load()
    if not back:
        return False
    try:
        synth_wav("你好")
        return True
    except Exception:  # pragma: no cover
        return False
