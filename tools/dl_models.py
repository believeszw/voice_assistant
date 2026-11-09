import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

HOST = "https://hf-mirror.com"
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")

FILES = [
    (
        "csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en",
        "sherpa-onnx-streaming-paraformer-bilingual-zh-en",
        ["encoder.int8.onnx", "decoder.int8.onnx", "decoder.onnx", "tokens.txt"],
    ),
    (
        "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        ["model.int8.onnx", "tokens.txt"],
    ),
]


def head_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers.get("Content-Length") or 0)


def download(repo, subdir, name):
    url = f"{HOST}/{repo}/resolve/main/{name}"
    outdir = os.path.join(ROOT, subdir)
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, name)
    try:
        size = head_size(url)
    except Exception as e:
        print(f"SKIP {name}: HEAD failed {type(e).__name__}: {e}")
        return
    if os.path.exists(outpath) and os.path.getsize(outpath) == size:
        print(f"OK   {name}: already present {size/1e6:.1f} MB")
        return
    tmp = outpath + ".part"
    got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    headers = {"User-Agent": "Mozilla/5.0"}
    if got:
        headers["Range"] = f"bytes={got}-"
    print(f"GET  {name}: {size/1e6:.1f} MB (resume at {got/1e6:.1f} MB)")
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    mode = "ab" if got else "wb"
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, mode) as f:
        last = 0.0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            now = time.time()
            if now - last > 2:
                last = now
                print(f"     {got/1e6:6.1f}/{size/1e6:.1f} MB", flush=True)
    if got != size:
        print(f"WARN {name}: got {got} of {size}, keep .part for resume")
        return
    os.replace(tmp, outpath)
    print(f"DONE {name}: {got} bytes in {time.time()-t0:.1f}s")


for repo, subdir, names in FILES:
    for name in names:
        download(repo, subdir, name)
print("ALL_DONE")
