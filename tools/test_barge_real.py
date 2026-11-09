"""真实声学闭环：扬声器放「助手播报」，麦克风收回声；「用户插话」按近场方式
直接叠加进麦克风信号（模拟用户离麦很近、远响于扬声器漏音）。

为什么这样测：本机只有一对扬声器，且麦克风离得远，用户声若也从扬声器放，
和助手声走同一条弱回声路径，AEC 无法区分「播报漏音」和「用户说话」；
真实车载/机器人场景里用户是近场声源，这才是有意义的验收条件。
助手回声仍走真实声学路径，用来验证 AEC 会把它压掉、不误触发。

用法：python tools/test_barge_real.py
"""
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm
from frontend import AudioFrontend, FRAME

SR = 16000
USER_DELAY = 1.2


def _read_wav(wav_bytes: bytes):
    import io
    import wave
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        ch = wf.getnchannels()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def _resample(x: np.ndarray, src: int, dst: int = SR):
    if src == dst:
        return x
    n = int(len(x) * dst / src)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)

try:
    import sounddevice as sd
except Exception as exc:
    print("sounddevice 不可用:", exc)
    sys.exit(1)


def _play_assistant(a16: np.ndarray, stop: threading.Event, far_sink=None):
    """只外放助手播报，并把同一块 PCM 推给 AEC 当参考。"""
    gain = 0.6
    chunk = FRAME
    with sd.OutputStream(samplerate=SR, channels=1, dtype="int16", blocksize=chunk) as st:
        pos = 0
        while pos < len(a16) and not stop.is_set():
            a = np.zeros(chunk, dtype=np.float32)
            seg = a16[pos:pos + chunk] * gain
            a[:len(seg)] = seg
            if far_sink is not None:
                far_sink(np.clip(a * 32768.0, -32768, 32767).astype(np.int16).tobytes())
            st.write(np.clip(a * 32768.0, -32768, 32767).astype(np.int16))
            pos += chunk


def main():
    out_dev = sd.default.device[1]
    print(f"输出设备: {out_dev} {sd.query_devices(out_dev)['name']}")
    print("合成 TTS ...")
    a_wav = llm.tts_wav("这是一段比较长的测试播报，用来验证用户中途打断的检测是否及时，语音助手应该立刻停下来听我说。")
    u_wav = llm.tts_wav("先停一下，帮我查一下现在几点。")
    a16 = _resample(_read_wav(a_wav)[0], _read_wav(a_wav)[1])
    u16 = _resample(_read_wav(u_wav)[0], _read_wav(u_wav)[1])
    # 用户近场说话：叠进麦克风信号，音量按「比扬声器漏音高一个量级」取
    user_gain = 3.0
    u16 = u16 * user_gain
    gap = int(USER_DELAY * SR)
    print(f"助手 {len(a16)/SR:.1f}s，用户 {len(u16)/SR:.1f}s，用户从 +{USER_DELAY}s 近场注入")

    stop = threading.Event()
    fe = AudioFrontend()
    th = threading.Thread(target=_play_assistant, args=(a16, stop, fe.push_far), daemon=True)
    th.start()

    barge_sample = None
    got = 0
    total = int((len(a16) / SR + 0.8) * SR)
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME) as st:
        while got < total:
            data, _ = st.read(FRAME)
            near = data.reshape(-1).astype(np.float32) / 32768.0
            # 用户声从 USER_DELAY 起叠加（近场）
            if got + FRAME > gap:
                off = max(0, got - gap)
                seg = u16[off:off + FRAME]
                if len(seg):
                    near[:len(seg)] += seg
            fe.process((np.clip(near, -1, 1) * 32768).astype(np.int16).tobytes())
            got += FRAME
            if fe.barge_in and barge_sample is None:
                barge_sample = got
                stop.set()
                break

    if barge_sample is None:
        print("FAIL：没有触发打断")
        return
    # 相对「用户真正开口」：u16 开头可能带合成器前导静音
    onset = 0
    win = int(0.05 * SR)
    for k in range(0, max(1, len(u16) - win), win):
        if float(np.sqrt(np.mean(u16[k:k + win] ** 2))) > 0.01:
            onset = k
            break
    true_start = gap + onset
    latency = (barge_sample - true_start) / SR
    print(f"首帧打断：麦克风 {barge_sample/SR:.2f}s，相对用户开口 +{latency:.2f}s，"
          f"erle={fe.last_erle:.1f}dB prob={fe.last_prob:.2f}")
    # 播放线程与采集线程启动有几毫秒~几十毫秒错位，给 ±0.15s 容差；上限 0.6s 是产品要求
    print("PASS" if -0.15 <= latency <= 0.6 else "FAIL（延迟超标）")


if __name__ == "__main__":
    main()
