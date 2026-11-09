"""自测：用 SAPI 合成语音，再喂给 Vosk，检查唤醒词与指令识别效果。

不依赖麦克风，适合在没有真人说话的环境下验证链路。
"""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import win32com.client  # noqa: E402
import pythoncom  # noqa: E402

from config import SAMPLE_RATE, TTS_VOICE  # noqa: E402
import asr  # noqa: E402
from intents import parse  # noqa: E402

OUT = Path(__file__).resolve().parent / "wav"
OUT.mkdir(exist_ok=True)


def synth(text: str, path: Path):
    pythoncom.CoInitialize()
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    for v in voice.GetVoices():
        if TTS_VOICE.lower() in v.GetDescription().lower():
            voice.Voice = v
            break
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(path), 3, False)  # SSFMCreateForWrite = 3
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()
    voice.AudioOutputStream = None


def load_16k(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    assert width == 2
    data = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels)[:, 0]
    if sr != SAMPLE_RATE:
        # 线性重采样即可，只用于自测
        duration = len(data) / sr
        n = int(duration * SAMPLE_RATE)
        x_old = np.linspace(0, duration, len(data), endpoint=False)
        x_new = np.linspace(0, duration, n, endpoint=False)
        data = np.interp(x_new, x_old, data).astype(np.int16)
    return data.tobytes()


def main():
    cases = [
        "小助手",
        "小助手打开记事本",
        "打开记事本",
        "现在几点了",
        "把音量调大一点",
        "下一首",
        "截个屏",
        "关闭计算器",
        "音量调到五十",
        "搜索天气",
        "显示桌面",
        "锁屏",
    ]
    print("=== 合成语音 -> Vosk 识别 ===")
    for i, text in enumerate(cases):
        path = OUT / f"case_{i}.wav"
        synth(text, path)
        pcm = load_16k(path)
        got = asr.transcribe_pcm(pcm)
        intent = parse(got)
        print(f"[{text}] -> 识别: {got!r} | 意图: {intent['action']} {intent.get('name') or intent.get('term') or intent.get('value') or ''}")

    print("\n=== 纯文本意图解析 ===")
    for text in ["帮我打开一下微信", "声音小一点", "取消关机", "复制今天下午三点开会",
                 "输入你好世界", "打开下载文件夹", "内存还剩多少", "你是谁"]:
        got = parse(text)
        print(f"[{text}] -> {got}")


if __name__ == "__main__":
    main()
