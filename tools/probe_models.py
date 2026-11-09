import io
import json
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

URLS = {
    "streaming_paraformer": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-paraformer-bilingual-zh-en.tar.bz2",
    "sense_voice": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
}


def probe(name, url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            size = int(r.headers.get("Content-Length") or 0)
            print(f"{name}: OK status={r.status} bytes={size} ({size/1e6:.1f} MB)")
    except Exception as e:
        print(f"{name}: FAIL {type(e).__name__}: {e}")


for k, u in URLS.items():
    probe(k, u)
