"""模拟一次“唤醒后连续对话”：把预先合成好的语音按时间顺序喂给助手。

不依赖麦克风，用来验证：一次唤醒 -> 多轮对话 -> 退出，以及云端 ASR/LLM/TTS 链路。
"""

import io
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio  # noqa: E402
import llm  # noqa: E402
from config import BLOCK_SIZE, SAMPLE_RATE  # noqa: E402

SILENCE = b"\x00" * (BLOCK_SIZE * 2)


def wav_to_pcm16k(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        ch, width, sr = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise RuntimeError("只支持 16 位 wav")
    data = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        data = data.reshape(-1, ch)[:, 0]
    if sr != SAMPLE_RATE:
        duration = len(data) / sr
        n = int(duration * SAMPLE_RATE)
        old = np.linspace(0, duration, len(data), endpoint=False)
        new = np.linspace(0, duration, n, endpoint=False)
        data = np.interp(new, old, data).astype(np.int16)
    return data.tobytes()


def pad_blocks(pcm: bytes) -> bytes:
    block_bytes = BLOCK_SIZE * 2
    if len(pcm) % block_bytes:
        pcm += b"\x00" * (block_bytes - len(pcm) % block_bytes)
    return pcm


class TapeMic:
    """按真实时间回放磁带上的音频块，接口和 audio.Mic 一致。"""

    def __init__(self, utterances):
        self.blocks = []
        for pcm in utterances:
            self.blocks.extend([SILENCE] * 8)          # 句前 0.4s 静音
            padded = pad_blocks(pcm)
            self.blocks.extend(padded[i:i + BLOCK_SIZE * 2]
                               for i in range(0, len(padded), BLOCK_SIZE * 2))
            self.blocks.extend([SILENCE] * 24)         # 句间 1.2s 静音
        self.blocks.extend([SILENCE] * 60)             # 结尾 3s 静音

    def start(self):
        pass

    def stop(self):
        pass

    def flush(self):
        # 丢掉队首的静音块，模拟“清掉上一句话的尾巴”
        while self.blocks and audio.rms_of(self.blocks[0]) < 200:
            self.blocks.pop(0)

    def read(self, timeout: float = 0.5):
        if not self.blocks:
            time.sleep(0.3)
            return None
        time.sleep(BLOCK_SIZE / SAMPLE_RATE)
        return self.blocks.pop(0)

    @property
    def name(self):
        return "TapeMic"


def main():
    texts = ["现在几点了", "今天吃啥", "把音量调大", "退出"]
    print("合成测试语音 ...")
    utterances = []
    for text in texts:
        wav = llm.tts_wav(text, style="正常语速，吐字清楚")
        pcm = wav_to_pcm16k(wav)
        utterances.append(pcm)
        print(f"  {text} -> {len(pcm)} 字节")

    tape = TapeMic(utterances)
    import assistant as assistant_mod
    from assistant import Assistant

    assistant_mod.audio.Mic = lambda *a, **k: tape   # 用磁带替换真麦克风

    bot = Assistant(text_mode=False, dry_run=False, use_hotkey=False, use_wake=True)
    print("\n=== 模拟连续对话（一次唤醒，四轮） ===")
    try:
        bot._session(tape)
    finally:
        bot.speaker.shutdown()
    print("\n=== 结束 ===")


if __name__ == "__main__":
    main()
