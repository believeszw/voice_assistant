"""下载端侧 TTS 模型（sherpa-onnx VITS MeloTTS 中英混合，int8 版）。

用法：C:\\va-venv\\Scripts\\python.exe tools\\_fetch_tts.py
输出：models/tts/vits-melo-tts-zh_en/，日志 tools/_fetch_tts.log（UTF-8）。
hf-mirror 链路不稳：支持断点续传（.part + Range）与自动重试，可重复运行。
"""
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DEST = BASE / "models" / "tts" / "vits-melo-tts-zh_en"
REPO = "https://hf-mirror.com/csukuangfj/vits-melo-tts-zh_en/resolve/main/"
LOG = BASE / "tools" / "_fetch_tts.log"
RETRIES = 6

FILES = {
    "model.int8.onnx": 53_520_000,
    "lexicon.txt": 6_840_000,
    "tokens.txt": 6_000,
    "date.fst": 60_000,
    "number.fst": 60_000,
    "phone.fst": 90_000,
    "new_heteronym.fst": 20_000,
}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def download_once(name, url, dest, tmp):
    have = tmp.stat().st_size if tmp.exists() else 0
    headers = {"User-Agent": "curl/8"}
    if have:
        headers["Range"] = f"bytes={have}-"
    with requests.get(url, stream=True, timeout=(20, 60), headers=headers) as r:
        if r.status_code == 416:  # 已经下完
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
                    mb = got / 1e6
                    log(f"  {name}: {mb:.0f}/{total / 1e6:.0f}MB "
                        f"{(got - have) / max(time.time() - t0, 1e-6) / 1e6:.2f}MB/s")
                    next_mark += 10 * 1024 * 1024
        return got >= total * 0.98
    return False


def download(name, approx):
    dest = DEST / name
    if dest.exists() and dest.stat().st_size >= approx * 0.9:
        log(f"skip {name} ({dest.stat().st_size / 1e6:.1f}MB)")
        return True
    url = REPO + name
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, RETRIES + 1):
        try:
            if download_once(name, url, dest, tmp):
                tmp.replace(dest)
                log(f"done {name} {dest.stat().st_size / 1e6:.1f}MB")
                return True
            log(f"  {name}: 不完整（尝试 {attempt}/{RETRIES}）")
        except Exception as exc:
            log(f"  {name}: 失败（尝试 {attempt}/{RETRIES}）{type(exc).__name__} {str(exc)[:100]}")
        time.sleep(2)
    return False


def main():
    log(f"start -> {DEST}")
    ok = 0
    for name, approx in FILES.items():
        if download(name, approx):
            ok += 1
    log(f"finished {ok}/{len(FILES)}")
    sys.exit(0 if ok == len(FILES) else 1)


if __name__ == "__main__":
    main()
