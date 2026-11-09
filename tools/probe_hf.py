import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

REPOS = [
    "csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en",
    "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
    "k2-fsa/sherpa-onnx-streaming-paraformer-bilingual-zh-en",
    "k2-fsa/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
]
HOSTS = ["https://huggingface.co", "https://hf-mirror.com"]

for host in HOSTS:
    for repo in REPOS:
        url = f"{host}/api/models/{repo}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.load(r)
            files = data.get("siblings", [])
            print(f"{host} {repo}: OK files={len(files)}")
            for f in files[:200]:
                name = f.get("rfilename", "")
                if name.endswith((".onnx", ".txt", ".json")) and "test" not in name:
                    print("   ", name)
        except Exception as e:
            print(f"{host} {repo}: FAIL {type(e).__name__}: {str(e)[:120]}")
    print("-" * 40)
