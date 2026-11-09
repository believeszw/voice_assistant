"""端到端声学测试：扬声器播放「唤醒词 + 指令」，麦克风采集，走完整链路。

使用已有 wav（避免 SAPI 合成在部分环境失败）：
  - 唤醒词：tools/kwswav/wake_你好小助手_0.wav
  - 指令：  tools/wav/case_3.wav（现在几点了）
用法：python tools/e2e_wake_test.py
"""

import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_RATE = 48000


def load(path: Path, peak: int = 30000):
    with wave.open(str(path), "rb") as wf:
        channels, sr = wf.getnchannels(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if channels > 1:
        data = data.reshape(-1, channels)[:, 0]
    maxv = float(np.abs(data).max()) or 1.0
    data = data / maxv * peak
    if sr != OUTPUT_RATE:
        duration = len(data) / sr
        n = int(duration * OUTPUT_RATE)
        x_old = np.linspace(0, duration, len(data), endpoint=False)
        x_new = np.linspace(0, duration, n, endpoint=False)
        data = np.interp(x_new, x_old, data)
    return np.clip(data, -32768, 32767).astype(np.int16)


def play(data):
    sd.play(data, OUTPUT_RATE)
    sd.wait()


def main():
    wake = ROOT / "tools" / "kwswav" / "wake_你好小助手_0.wav"
    cmd = ROOT / "tools" / "wav" / "case_3.wav"
    if not wake.exists() or not cmd.exists():
        print("缺少测试音频:", wake, cmd)
        return
    print(f"[e2e] 扬声器输出设备：{sd.query_devices(kind='output')['name']}")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["MIC_GAIN"] = "2"
    proc = subprocess.Popen(
        [sys.executable, "-u", "assistant.py", "--dry-run", "--no-hotkey"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, text=True, encoding="utf-8", errors="replace",
    )

    time.sleep(12)  # 等模型加载 + 启动提示说完
    print("[e2e] 播放唤醒词")
    play(load(wake))
    time.sleep(3)
    print("[e2e] 播放指令")
    play(load(cmd))
    time.sleep(8)
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()

    out_file = ROOT / "e2e_out.txt"
    out_file.write_text(out or "", encoding="utf-8")
    print("[e2e] 子进程输出已写入", out_file)
    keys = ("麦克风", "唤醒", "指令", "识别", "助手", "状态", "Traceback", "错误")
    for line in (out or "").splitlines():
        if any(k in line for k in keys):
            print("  |", line)


if __name__ == "__main__":
    main()
