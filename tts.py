"""语音输出：优先用小米 MiMo 的云端音色，失败/超时退回端侧 VITS，最后退 Windows SAPI。

Speaker 用一个独立线程串行朗读，支持 stop() 打断。
双路策略（选型 §4 / §5）：云端主路 → 端侧 sherpa-onnx VITS（离线、可暂停）→ SAPI 极简兜底。
"""

import io
import os
import queue
import subprocess
import tempfile
import threading
import time
import wave
from collections import deque

import numpy as np

import llm
import tts_local
from config import (CLOUD_ENABLED, CLOUD_TTS, TTS_CLOUD_TIMEOUT, TTS_LOCAL_ENABLED,
                    TTS_LOCAL_FIRST, TTS_STYLE, TTS_VOICE, TTS_VOICE_NAME, WAKE_ACK)

_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_QUICK_WAV = None
_QUICK_WAV_LOADED = False


def _quick_wav():
    """预生成的唤醒回应音频（assets/wake_ack.wav），避免每次唤醒等云端合成。"""
    global _QUICK_WAV, _QUICK_WAV_LOADED
    if not _QUICK_WAV_LOADED:
        _QUICK_WAV_LOADED = True
        try:
            with open(os.path.join(_ASSET_DIR, "wake_ack.wav"), "rb") as f:
                _QUICK_WAV = f.read()
        except Exception:
            _QUICK_WAV = None
    return _QUICK_WAV


try:
    import pythoncom
    import win32com.client
    _HAS_SAPI = True
except Exception:  # pragma: no cover
    _HAS_SAPI = False

try:
    import sounddevice as sd
    _HAS_SD = True
except Exception:  # pragma: no cover
    _HAS_SD = False

SVSF_ASYNC = 1
SVSF_PURGE = 2

_CACHE = {}
_CACHE_ORDER = []
_CACHE_LOCK = threading.Lock()


def _tmp_wav(tag: str) -> str:
    """合成用的临时 wav 路径。

    不写系统 %TEMP%：本机沙箱下那里可能被拒写（Errno 13），
    统一放项目内 .tts_tmp/，失败再退回系统临时目录。
    """
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tts_tmp")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = tempfile.gettempdir()
    return os.path.join(base, "%s_%d.wav" % (tag, threading.get_ident()))


def _ps_render_wav(text: str) -> bytes:
    """用 Windows 自带 System.Speech 把文字合成 wav（COM 路径坏时的兜底）。

    venv 里 pywin32 的 SAPI SpFileStream 偶发 0x80045040（不支持的格式），
    System.Speech 走的是同一个 SAPI 引擎，但不需要 COM 属性绑定，稳定得多。
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "tools", "ps_tts.ps1")
    if not os.path.exists(script):
        return b""
    path = _tmp_wav("dsh_ps")
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script, "-Out", path, "-Text", text],
            check=False, capture_output=True, timeout=90)
        with open(path, "rb") as f:
            return f.read()
    except Exception as exc:  # pragma: no cover
        print("[TTS] PowerShell 合成失败:", str(exc)[:120])
        return b""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _read_wav_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            data = f.read()
        return data if data[:4] == b"RIFF" else b""
    except OSError:
        return b""


def _sapi_render_wav(text: str, voice) -> bytes:
    """把 SAPI 朗读渲染成内存 wav，让本地兜底也能暂停/继续、并给 AEC 提供参考。

    优先走 COM（快）；COM 报错时退回 System.Speech（PowerShell）渲染。
    """
    if not text:
        return b""
    if _HAS_SAPI and voice is not None:
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        path = _tmp_wav("dsh_sapi")
        old = None
        ok = False
        try:
            old = voice.AudioOutputStream
            stream.Open(path, 3, False)  # SSFMCreateForWrite
            voice.AudioOutputStream = stream
            voice.Speak(text, 0)         # 同步渲染到文件
            ok = True
        except Exception as exc:  # pragma: no cover
            print("[TTS] SAPI 渲染失败，改用 System.Speech:", str(exc)[:120])
        finally:
            # 必须先关文件流再读：SAPI 写入期间文件被占用，直接读会 PermissionError
            try:
                if old is not None:
                    voice.AudioOutputStream = old
            except Exception:
                pass
            try:
                stream.Close()
            except Exception:
                pass
            data = _read_wav_bytes(path)
            try:
                os.remove(path)
            except OSError:
                pass
            if ok and data:
                return data
    return _ps_render_wav(text)


def _remember(text: str, wav: bytes):
    with _CACHE_LOCK:
        _CACHE[text] = wav
        _CACHE_ORDER.append(text)
        while len(_CACHE_ORDER) > 80:
            old = _CACHE_ORDER.pop(0)
            _CACHE.pop(old, None)


def _play_wav(wav_bytes: bytes, stop_event: threading.Event, far_sink=None,
              pause_event: threading.Event = None):
    """播放 wav 字节；stop_event 置位时停止，pause_event 置位时暂停（可恢复）。

    far_sink: 可选回调，按块把「实际正在播的参考 PCM」交给回声抑制模块。
    暂停/恢复时参考信号也跟着停，AEC 的 far/near 时间线不会错位。
    """
    if not _HAS_SD:
        raise RuntimeError("sounddevice 不可用")
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise RuntimeError(f"不支持的位宽 {width}")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels)
        data = data.mean(axis=1)
    if not len(data):
        return
    # AEC 只认 16k 参考；云端 TTS 可能是 24k，按块重采样后推给它
    if far_sink is not None and rate != 16000:
        n = max(1, int(len(data) * 16000 / rate))
        ref_data = np.interp(np.linspace(0, len(data) - 1, n),
                             np.arange(len(data)), data)
    else:
        ref_data = data
    block = max(1, int(rate * 0.05))
    stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32")
    stream.start()
    # AEC 参考必须和「耳朵听到」的时刻对齐：OutputStream 有几十到几百毫秒的
    # 播放延迟，若在 write 时立刻推参考，AEC3 看到的 far 会比麦克风收到的回声早，
    # 反而抵消不掉（真实设备上表现为播报时残留回声很大）。
    try:
        out_lat = float(getattr(stream, "latency", 0.0) or 0.0)
    except Exception:  # pragma: no cover
        out_lat = 0.0
    ref_delay_blocks = max(0, int(round(out_lat * rate / block)))
    pending_refs = deque()

    def _emit_ref(ref_bytes):
        if far_sink is not None and ref_bytes:
            try:
                far_sink(ref_bytes)
            except Exception as exc:  # pragma: no cover
                print("[TTS] 参考信号推送失败:", str(exc)[:120])

    i = 0
    try:
        while i < len(data):
            if stop_event.is_set():
                break
            if pause_event is not None and pause_event.is_set():
                time.sleep(0.02)
                continue
            n = min(block, len(data) - i)
            chunk = data[i:i + n]
            stream.write(chunk.reshape(-1, 1))
            if far_sink is not None:
                try:
                    j0 = int(i * 16000 / rate)
                    j1 = max(j0 + 1, int((i + n) * 16000 / rate))
                    seg = ref_data[j0:j1]
                    if len(seg):
                        pending_refs.append(np.clip(seg * 32768.0, -32768,
                                                    32767).astype(np.int16).tobytes())
                        # 延迟 ref_delay_blocks 个块再推，使参考时间线与听到的时刻一致
                        while len(pending_refs) > ref_delay_blocks:
                            _emit_ref(pending_refs.popleft())
                except Exception as exc:  # pragma: no cover
                    print("[TTS] 参考信号推送失败:", str(exc)[:120])
            i += n
        if not stop_event.is_set():
            while pending_refs:
                _emit_ref(pending_refs.popleft())
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass


class Speaker:
    def __init__(self):
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._playing = False
        self.far_sink = None          # 由 Assistant 注入：把播放 PCM 喂给 AEC
        self._busy = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def busy(self) -> bool:
        return self._q.qsize() > 0 or self._busy.locked()

    # ------------------------------------------------ worker
    def _worker(self):
        voice = None
        if _HAS_SAPI:
            try:
                pythoncom.CoInitialize()
                voice = win32com.client.Dispatch("SAPI.SpVoice")
                for v in voice.GetVoices():
                    if TTS_VOICE.lower() in v.GetDescription().lower():
                        voice.Voice = v
                        break
                voice.Volume = 100
                voice.Rate = 0
            except Exception as exc:  # pragma: no cover
                print("[TTS] SAPI 初始化失败:", exc)
                voice = None

        while True:
            item = self._q.get()
            if item is None:
                break
            text, done, mode = item
            self._stop.clear()
            self._pause.clear()
            self._busy.acquire()
            try:
                if mode == "quick":
                    wav = _quick_wav() if text == WAKE_ACK else None
                    self._play_bytes(wav, text, voice)
                elif TTS_LOCAL_FIRST:
                    # 强制端侧（对比测速 / 断网演示）
                    self._speak_local_dual(text, voice)
                elif CLOUD_ENABLED and CLOUD_TTS and llm.available():
                    if not self._speak_cloud(text):
                        self._speak_local_dual(text, voice)
                else:
                    self._speak_local_dual(text, voice)
            except Exception as exc:  # pragma: no cover
                print("[TTS] 朗读失败:", exc)
                try:
                    self._speak_local_dual(text, voice)
                except Exception:
                    pass
            finally:
                self._busy.release()
                if done is not None:
                    done.set()

    def _speak_cloud(self, text: str) -> bool:
        wav = _CACHE.get(text)
        if wav is None:
            try:
                # 弱网时整段合成会拖很久：超过 TTS_CLOUD_TIMEOUT 就放弃，交给端侧
                wav = llm.tts_wav(text, voice=TTS_VOICE_NAME, style=TTS_STYLE,
                                  timeout=TTS_CLOUD_TIMEOUT)
            except Exception as exc:
                print("[TTS] 云端合成失败/超时，改用端侧:", str(exc)[:120])
                return False
            if not wav:
                return False
            _remember(text, wav)
        try:
            self._playing = True
            try:
                _play_wav(wav, self._stop, self.far_sink, self._pause)
            finally:
                self._playing = False
            return True
        except Exception as exc:  # pragma: no cover
            print("[TTS] 播放失败，改用本地:", str(exc)[:120])
            return False

    def _play_bytes(self, wav, text, voice) -> bool:
        if wav and _HAS_SD:
            self._playing = True
            try:
                _play_wav(wav, self._stop, self.far_sink, self._pause)
            finally:
                self._playing = False
            return True
        self._speak_local(text, voice)
        return True

    def _speak_local(self, text: str, voice) -> bool:
        """本地兜底：先渲染成 wav 再走统一播放（可暂停 + 推 AEC 参考）。"""
        wav = _CACHE.get(text)
        if wav is None and _HAS_SAPI and voice is not None:
            wav = _sapi_render_wav(text, voice)
            if wav:
                _remember(text, wav)
        if wav and _HAS_SD:
            self._playing = True
            try:
                _play_wav(wav, self._stop, self.far_sink, self._pause)
            finally:
                self._playing = False
            return True
        self._speak_sapi(text, voice)
        return True

    def _speak_local_dual(self, text: str, voice) -> bool:
        """端侧兜底两级：Piper/VITS 离线合成（自然、可离线）→ SAPI（最简兜底）。"""
        if TTS_LOCAL_ENABLED and self._speak_vits(text):
            return True
        return self._speak_local(text, voice)

    def _speak_vits(self, text: str) -> bool:
        """端侧合成 + 统一播放（AEC 参考/打断/暂停都复用 _play_wav）。

        tts_local 内部按 Piper → sherpa-onnx VITS 顺序选后端，这里不关心具体实现。
        """
        if not _HAS_SD or not tts_local.available():
            return False
        wav = _CACHE.get(text)
        if wav is None:
            wav = tts_local.synth_wav(text)
            if not wav:
                return False
            _remember(text, wav)
            stats = tts_local.last_stats()
            if stats.get("synth_ms"):
                print(f"[TTS] 端侧合成 {stats['synth_ms']:.0f} ms"
                      f"（{stats.get('backend', 'local')}，{stats.get('text_len', 0)} 字 → "
                      f"{stats.get('audio_seconds', 0):.1f} s 音频）")
        self._playing = True
        try:
            _play_wav(wav, self._stop, self.far_sink, self._pause)
        finally:
            self._playing = False
        return True

    def _speak_sapi(self, text: str, voice):
        if not _HAS_SAPI or voice is None:
            print(f"[助手] {text}")
            return
        try:
            voice.Speak(text, SVSF_ASYNC)
            while True:
                if self._stop.is_set():
                    voice.Speak("", SVSF_ASYNC | SVSF_PURGE)
                    break
                if voice.WaitUntilDone(50):
                    break
        except Exception as exc:  # pragma: no cover
            print("[TTS] SAPI 朗读失败:", exc)

    # ------------------------------------------------ 对外
    def say(self, text: str):
        if not text:
            return
        print(f"[助手] {text}")
        done = threading.Event()
        self._q.put((text, done, "normal"))
        if not done.wait(timeout=180):  # 防 worker 异常导致永久阻塞
            print("[TTS] 朗读超时（180s），跳过")

    def say_quick(self, text: str):
        """低延迟短句（唤醒回应「我在」）：优先播预生成音频，没有再退本地 SAPI。"""
        if not text:
            return
        print(f"[助手] {text}")
        wav = _quick_wav() if text == WAKE_ACK else None
        if wav and _HAS_SD:
            try:
                _play_wav(wav, self._stop, self.far_sink)
                return
            except Exception as exc:  # pragma: no cover
                print("[TTS] 短句播放失败，改用本地:", str(exc)[:120])
        done = threading.Event()
        self._q.put((text, done, "quick"))
        done.wait()

    def say_async(self, text: str):
        """异步朗读，返回一个 done 事件（读完/被打断后置位）。"""
        done = threading.Event()
        if not text:
            done.set()
            return done
        print(f"[助手] {text}")
        self._q.put((text, done, "normal"))
        return done

    def playing(self) -> bool:
        return self._playing

    def pause(self) -> bool:
        """暂停当前云端播报（可恢复）。SAPI 路径不支持暂停，返回 False。"""
        if not self._playing:
            return False
        self._pause.set()
        return True

    def resume(self):
        self._pause.clear()

    def discard(self):
        """真打断：丢掉当前这句剩下的部分。"""
        self._pause.clear()
        self._stop.set()

    def stop(self):
        self._stop.set()
        if _HAS_SD:
            try:
                sd.stop()
            except Exception:
                pass

    def shutdown(self):
        self._q.put(None)
