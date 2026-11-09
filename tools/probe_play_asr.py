# -*- coding: utf-8 -*-
"""播放电平对 ASR 的影响：同一句话不同增益外放（播放同时录音），识别结果对比。"""
import os
import sys
import threading
import time
import wave

import numpy as np
import sounddevice as sd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions
import audio
import frontend

SAMPLES = ["现在几点了", "退出", "打开记事本", "把音量调到三十", "讲个笑话"]
GAINS = [1.0, 2.0, 3.0, 6.0]
HERE = os.path.dirname(os.path.abspath(__file__))


def load_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(data) * 16000 / sr)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    return data


def render(text):
    path = os.path.join(HERE, "probe_tts.wav")
    try:
        os.remove(path)
    except OSError:
        pass
    import win32com.client
    sapi = win32com.client.Dispatch("SAPI.SpVoice")
    fs = win32com.client.Dispatch("SAPI.SpFileStream")
    fs.Open(path, 3, False)
    old = sapi.AudioOutputStream
    sapi.AudioOutputStream = fs
    sapi.Speak(text)
    fs.Close()
    sapi.AudioOutputStream = old
    return path


def main():
    from asr_local import TwoPassASR
    asr = TwoPassASR()
    actions.mute(False)
    actions.set_volume(100)
    mic = audio.Mic()
    mic.start()
    out = os.path.join(HERE, "probe_play_asr.out")
    with open(out, "w", encoding="utf-8") as f:
        for text in SAMPLES:
            path = render(text)
            data = load_wav(path)
            peak = float(np.max(np.abs(data))) or 1.0
            for gain in GAINS:
                scaled = np.clip(data * gain, -1.0, 1.0)
                time.sleep(0.3)
                mic.flush()
                holder = {}

                def rec():
                    holder["r"] = audio.record_utterance(
                        mic, max_seconds=4.0, silence_seconds=0.7, start_timeout=1.5)

                th = threading.Thread(target=rec)
                th.start()
                time.sleep(0.15)
                sd.play(scaled, 16000, blocking=True)
                th.join(timeout=8)
                pcm, secs, started = holder.get("r", (b"", 0.0, False))
                rms = audio.rms_of(pcm) if pcm else 0.0
                got = ""
                if pcm:
                    pcm = frontend.enhance_pcm(pcm) or pcm
                    asr.start()
                    got, _eng = asr.finish(pcm)
                line = (f"{text!r} gain={gain} rms={rms:.4f} "
                        f"started={started} rec={got!r} peak_in={peak:.2f}")
                print(line)
                f.write(line + "\n")
                f.flush()
    mic.stop()
    print("OUT", out)


if __name__ == "__main__":
    main()
