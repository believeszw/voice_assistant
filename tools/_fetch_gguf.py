"""下载端侧 NLU 模型：Qwen2.5-1.5B-Instruct Q4_K_M GGUF（ModelScope，速度快）。

用法：C:\\va-venv\\Scripts\\python.exe tools\\_fetch_gguf.py
输出：models/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf，日志 tools/_fetch_gguf.log。
"""
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DEST = BASE / "models" / "llm" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
URL = ("https://modelscope.cn/models/qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/master/"
       "qwen2.5-1.5b-instruct-q4_k_m.gguf")
LOG = BASE / "tools" / "_fetch_gguf.log"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    log(f"start -> {DEST}")
    if DEST.exists() and DEST.stat().st_size > 900_000_000:
        log(f"skip exists {DEST.stat().st_size / 1e6:.0f}MB")
        return
    tmp = DEST.with_suffix(".gguf.part")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    got = 0
    next_mark = 100
    try:
        with requests.get(URL, stream=True, timeout=(20, 180),
                          headers={"User-Agent": "curl/8"}) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            log(f"http {r.status_code} total={total / 1e6:.0f}MB")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 512):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    got += len(chunk)
                    mb = got / 1e6
                    if mb >= next_mark:
                        log(f"  {mb:.0f}/{total / 1e6:.0f}MB {mb / max(time.time() - t0, 1e-6):.1f}MB/s")
                        next_mark += 100
        tmp.replace(DEST)
        log(f"done {got / 1e6:.0f}MB in {time.time() - t0:.0f}s")
    except Exception as exc:
        log(f"FAIL {type(exc).__name__} {exc}")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
