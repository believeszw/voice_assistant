"""下载 llama.cpp Windows CPU 预编译包并解压到 tools/llama/（端侧 NLU 运行时）。

用法：C:\\va-venv\\Scripts\\python.exe tools\\_fetch_llama.py
日志：tools/_fetch_llama.log（UTF-8）。
"""
import sys
import time
import zipfile
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
TAG_URL = ("https://gh-proxy.com/https://github.com/ggml-org/llama.cpp/releases/download/"
           "v0.9.0/nightly-tag.txt")
DEST = BASE / "tools" / "llama"
ZIP = BASE / "tools" / "_llama.zip"
LOG = BASE / "tools" / "_fetch_llama.log"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    log(f"start -> {DEST}")
    tag = requests.get(TAG_URL, timeout=30, headers={"User-Agent": "curl/8"}).text.strip()
    log(f"nightly tag: {tag}")
    url = (f"https://gh-proxy.com/https://github.com/ggml-org/llama.cpp/releases/download/"
           f"{tag}/llama-{tag}-bin-win-cpu-x64.zip")
    if not ZIP.exists() or ZIP.stat().st_size < 20_000_000:
        t0 = time.time()
        got = 0
        with requests.get(url, stream=True, timeout=(20, 120),
                          headers={"User-Agent": "curl/8"}) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            with open(ZIP, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
                        got += len(chunk)
        log(f"zip {got / 1e6:.1f}MB in {time.time() - t0:.1f}s")
    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP) as zf:
        names = zf.namelist()
        log(f"zip entries {len(names)}: {names[:10]}")
        zf.extractall(DEST)
    exes = sorted(p.name for p in DEST.rglob("*.exe"))
    log(f"exe: {exes}")
    servers = list(DEST.rglob("llama-server.exe"))
    log(f"llama-server: {servers}")
    sys.exit(0 if servers else 1)


if __name__ == "__main__":
    main()
