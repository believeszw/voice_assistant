"""探测 webrtc-audio-processing v2 源码包可下载性（freedesktop gitlab 及镜像）。"""
import io
import sys
import tarfile
import urllib.request

CANDIDATES = [
    "https://gitlab.freedesktop.org/pulseaudio/webrtc-audio-processing/-/archive/v2.1/webrtc-audio-processing-v2.1.tar.gz",
    "https://gitlab.freedesktop.org/pulseaudio/webrtc-audio-processing/-/archive/v2.2/webrtc-audio-processing-v2.2.tar.gz",
    "https://github.com/webrtc-audio-processing/webrtc-audio-processing/archive/refs/tags/v2.1.tar.gz",
]

DEST = "tools/wap2_src"


def try_one(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-voice/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    print("OK", url, "bytes", len(data))
    import os
    os.makedirs(DEST, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        tf.extractall(DEST)
    print("extracted to", DEST)
    return True


for u in CANDIDATES:
    try:
        if try_one(u):
            break
    except Exception as exc:
        print("FAIL", u, type(exc).__name__, str(exc)[:120])
