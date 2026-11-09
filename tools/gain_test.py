"""测试麦克风增益：把录到的音频放大不同倍数，看 Vosk 识别效果。"""

import sys
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audio  # noqa: E402
import asr  # noqa: E402

WAV = ROOT / "tools" / "wav" / "probe.wav"


def main():
    import wave

    with wave.open(str(WAV), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.int32)
    print(f"原始 rms={audio.rms_of(pcm):.0f}")
    for gain in (1, 2, 3, 4, 6, 8):
        boosted = np.clip(arr * gain, -32768, 32767).astype(np.int16).tobytes()
        print(f"gain={gain}: rms={audio.rms_of(boosted):.0f} 识别={asr.transcribe_pcm(boosted)!r}")

    # 顺便看看麦克风音量能不能调
    try:
        from pycaw.pycaw import AudioUtilities
        mic = AudioUtilities.GetMicrophone()
        print("麦克风:", mic.FriendlyName, "音量:", mic.volume_percent, "mute:", mic.EndpointVolume.GetMute())
        mic.EndpointVolume.SetMasterVolumeLevelScalar(1.0, None)
        print("麦克风音量已设为 100%，现在:", mic.volume_percent)
    except Exception as exc:
        print("麦克风音量控制失败:", exc)

    print("输出设备:", sd.query_devices(kind="output")["name"],
          "默认音量检查略")


if __name__ == "__main__":
    main()
