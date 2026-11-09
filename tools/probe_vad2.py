"""调试 Silero VAD 输出：确认模型输入口径（采样率/幅度/状态）。"""

import os
import sys
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parent.parent
SP = Path(os.environ.get("SP", "")) if os.environ.get("SP") else None
VOICE = ROOT / "models" / "silero" / "silero_vad.onnx"
PKG = Path(r"C:/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/site-packages/silero_vad/data")


def load(name: str, sr_out: int = 16000):
    w = wave.open(str(ROOT / "tools" / "wav" / name))
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if sr != sr_out:
        n = int(round(len(x) * sr_out / sr))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def run(model_path, x, sr=16000):
    s = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    st = np.zeros((2, 1, 128), dtype=np.float32)
    probs = []
    for i in range(0, len(x) - 512, 512):
        out = s.run(None, {"input": x[i:i + 512].reshape(1, 512),
                           "state": st, "sr": np.array(sr, dtype=np.int64)})
        st = out[1]
        probs.append(float(out[0].reshape(-1)[0]))
    return np.array(probs)


def main():
    x = load("case_1.wav")
    print("dur", round(len(x) / 16000, 2), "rms", round(float(np.sqrt(np.mean(x ** 2))), 4))
    win = 16000
    best = max(range(0, max(1, len(x) - win), 800), key=lambda i: float(np.mean(x[i:i + win] ** 2)))
    seg = x[best:best + win]
    print("loud pos", best, "rms", round(float(np.sqrt(np.mean(seg ** 2))), 4))
    for name in ["silero_vad.onnx", "silero_vad_16k_op15.onnx", "silero_vad_op18_ifless.onnx"]:
        p = PKG / name
        if not p.exists():
            p = VOICE
        for tag, data in (("raw", seg), ("x10", np.clip(seg * 10, -1, 1)), ("int16", np.clip(seg * 32768, -32768, 32767) / 32768.0)):
            pr = run(p, data)
            print(name, tag, "max", round(float(pr.max()), 3), "mean", round(float(pr.mean()), 4))
    # 正常语音文件整体
    print("case_2 all frames:", np.round(run(VOICE, load("case_2.wav"))[:20], 3))


if __name__ == "__main__":
    main()
