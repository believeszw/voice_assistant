import sys

out = []
try:
    import sounddevice, vosk, sherpa_onnx, onnxruntime, win32com, pycaw, psutil, pyperclip, requests  # noqa
    out.append("DEPS_OK")
except Exception as e:  # noqa: BLE001
    out.append(f"DEPS_FAIL: {type(e).__name__}: {e}")

try:
    data = open(r"tools\pip_install.out", "rb").read()
    try:
        text = data.decode("utf-16")
    except Exception:  # noqa: BLE001
        text = data.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    out.append("PIP_LOG_TAIL:")
    out.extend(lines[-25:])
except Exception as e:  # noqa: BLE001
    out.append(f"LOG_FAIL: {type(e).__name__}: {e}")

open(r"tools\deps_check.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out[:3]))
