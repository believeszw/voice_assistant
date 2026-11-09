"""麦克风探针：录一段“自己说话”的音频，检查麦克风能否听清 TTS。"""

import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audio  # noqa: E402
from tts import Speaker  # noqa: E402
import asr  # noqa: E402

OUT = ROOT / "tools" / "wav" / "probe.wav"
OUT.parent.mkdir(exist_ok=True)


def main():
    speaker = Speaker("Microsoft Huihui Desktop")
    seconds = 10
    chunks = []

    def record():
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16") as stream:
            start = time.time()
            while time.time() - start < seconds:
                data, _ = stream.read(800)  # 50ms
                chunks.append(bytes(data))

    def speak():
        time.sleep(2.0)
        speaker.say("小助手")
        time.sleep(1.5)
        speaker.say("现在几点了")

    t1 = threading.Thread(target=record)
    t2 = threading.Thread(target=speak)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    speaker.shutdown()

    pcm = b"".join(chunks)
    arr = np.frombuffer(pcm, dtype=np.int16)
    print(f"采集 {len(pcm)/32000:.1f}s，rms={audio.rms_of(pcm):.0f}，peak={int(np.abs(arr).max())}")

    with wave.open(str(OUT), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm)
    print("已保存", OUT)

    text = asr.transcribe_pcm(pcm)
    print("识别结果:", repr(text))


if __name__ == "__main__":
    main()
