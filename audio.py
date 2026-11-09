"""麦克风采集与简单的能量 VAD。"""

import queue

import numpy as np
import sounddevice as sd

from config import BLOCK_SIZE, MIC_GAIN, MIC_NAME, SAMPLE_RATE


def rms_of(data: bytes) -> float:
    if not data:
        return 0.0
    x = np.frombuffer(data, dtype=np.int16).astype(np.float64)
    return float(np.sqrt((x * x).mean()))


def find_input_device(name_hint: str = MIC_NAME):
    """按名字找输入设备，找不到就用系统默认。"""
    devices = sd.query_devices()
    if name_hint:
        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] > 0 and name_hint.lower() in dev["name"].lower():
                return idx
    default = sd.default.device[0]
    if default is not None and default >= 0:
        return default
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            return idx
    raise RuntimeError("没有找到可用的麦克风")


class Mic:
    """把 sounddevice 回调转成阻塞队列，方便主循环按块读取。"""

    def __init__(self, device=None, samplerate: int = SAMPLE_RATE):
        self.device = find_input_device() if device is None else device
        self.samplerate = samplerate
        self._q: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._stream = None
        self._overflow = 0

    def _callback(self, indata, frames, time_info, status):
        if status:
            self._overflow += 1
        try:
            self._q.put_nowait(bytes(indata))
        except queue.Full:
            pass

    def start(self):
        if self._stream is not None:
            return
        self._stream = sd.RawInputStream(
            samplerate=self.samplerate,
            blocksize=BLOCK_SIZE,
            device=self.device,
            dtype="int16",
            channels=1,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self, timeout: float = 0.5):
        try:
            block = self._q.get(timeout=timeout)
        except queue.Empty:
            return None
        if MIC_GAIN != 1.0 and block:
            x = np.frombuffer(block, dtype=np.int16).astype(np.float32) * MIC_GAIN
            block = np.clip(x, -32768, 32767).astype(np.int16).tobytes()
        return block

    def flush(self):
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    @property
    def name(self):
        return sd.query_devices(self.device)["name"]

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


class EnergyVAD:
    """自适应噪声底的能量 VAD，够用且不引入额外依赖。"""

    def __init__(self):
        self.floor = 150.0
        self._warm = 0

    def level(self, block: bytes) -> float:
        return rms_of(block)

    def is_speech(self, level: float) -> bool:
        threshold = max(self.floor * 3.0, 220.0)
        return level > threshold

    def update_noise(self, level: float):
        # 只在明显低于语音时缓慢更新噪声底
        if level < max(self.floor * 2.5, 400.0):
            self.floor = 0.95 * self.floor + 0.05 * level


def record_utterance(mic: Mic, max_seconds: float = 8.0,
                     silence_seconds: float = 0.8,
                     start_timeout: float = 3.0,
                     vad: EnergyVAD = None,
                     on_block=None,
                     pre_pcm: bytes = b""):
    """录一句话：等到有声音，再等到静音结束。返回 (pcm_bytes, seconds, started)。

    on_block(block)：语音开始后每块回调一次，用于流式识别出草稿。
    pre_pcm：打断瞬间已经录到的开头音频（预录缓冲）。传了它就直接接在
    本次录音前面，并视为「已经在说话」，这样用户打断后的第一句话不会
    被切掉开头几个字。
    """
    vad = vad or EnergyVAD()
    mic.flush()
    block_sec = BLOCK_SIZE / SAMPLE_RATE
    frames = [pre_pcm] if pre_pcm else []
    started = bool(pre_pcm)
    silence = 0.0
    waited = 0.0
    deadline = max_seconds

    while True:
        block = mic.read(timeout=0.3)
        if block is None:
            if not started:
                waited += 0.3
                if waited >= start_timeout:
                    return b"", 0.0, False
            continue
        level = vad.level(block)
        if not started:
            vad.update_noise(level)
            if vad.is_speech(level):
                started = True
                frames.append(block)
                if on_block is not None:
                    on_block(block)
            else:
                waited += block_sec
                if waited >= start_timeout:
                    return b"", 0.0, False
        else:
            frames.append(block)
            if on_block is not None:
                on_block(block)
            if vad.is_speech(level):
                silence = 0.0
            else:
                silence += block_sec
                if silence >= silence_seconds:
                    break
        if len(frames) * block_sec >= deadline:
            break

    pcm = b"".join(frames)
    return pcm, len(pcm) / (SAMPLE_RATE * 2), started


def save_wav(path: str, pcm: bytes, samplerate: int = SAMPLE_RATE):
    import wave
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(pcm)


if __name__ == "__main__":
    with Mic() as mic:
        print("设备:", mic.name)
        print("说话测试（3 秒）...")
        pcm, secs, ok = record_utterance(mic, max_seconds=3, start_timeout=3)
        print("录到", round(secs, 2), "秒, 有语音:", ok)
        if ok:
            save_wav("test_record.wav", pcm)
            print("已保存 test_record.wav")
