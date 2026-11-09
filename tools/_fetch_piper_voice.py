"""下载 Piper 中文语音 zh_CN-huayan-medium（hf-mirror，支持续传）。"""
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DEST = BASE / "models" / "tts" / "piper-zh_CN-huayan-medium"
LOG = BASE / "tools" / "_fetch_piper.log"
REPO = "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/"
FILES = {"zh_CN-huayan-medium.onnx": 63_201_294, "zh_CN-huayan-medium.onnx.json": 4_000}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def download(name):
    url = REPO + name
    dest = DEST / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 7):
        try:
            have = tmp.stat().st_size if tmp.exists() else 0
            if dest.exists() and dest.stat().st_size > 1000:
                log(f"skip {name}")
                return True
            headers = {"User-Agent": "curl/8"}
            if have:
                headers["Range"] = f"bytes={have}-"
            with requests.get(url, stream=True, timeout=(20, 60), headers=headers) as r:
                if r.status_code == 416:
                    tmp.replace(dest)
                    return True
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0) + have
                mode = "ab" if r.status_code == 206 else "wb"
                if mode == "wb":
                    have = 0
                got = have
                t0 = time.time()
                next_mark = (got // (10 * 1024 * 1024) + 1) * 10 * 1024 * 1024
                with open(tmp, mode) as fh:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        got += len(chunk)
                        if got >= next_mark:
                            log(f"  {name}: {got / 1e6:.0f}/{total / 1e6:.0f}MB "
                                f"{(got - have) / max(time.time() - t0, 1e-6) / 1e6:.2f}MB/s")
                            next_mark += 10 * 1024 * 1024
                if got >= total * 0.98:
                    tmp.replace(dest)
                    log(f"done {name} {dest.stat().st_size / 1e6:.1f}MB")
                    return True
                log(f"  {name}: 不完整 {got}/{total}（尝试 {attempt}/6）")
        except Exception as exc:
            log(f"  {name}: 失败（尝试 {attempt}/6）{type(exc).__name__} {str(exc)[:100]}")
        time.sleep(2)
    return False


def main():
    log(f"start -> {DEST}")
    ok = sum(1 for name in FILES if download(name))
    log(f"finished {ok}/{len(FILES)}")
    return 0 if ok == len(FILES) else 1


if __name__ == "__main__":
    sys.exit(main())
