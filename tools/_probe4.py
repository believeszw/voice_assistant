"""临时探测：llama.cpp nightly tag & asset URL；torch 是否可用；ModelScope ONNX LLM 候选。"""
import json

import requests

UA = {"User-Agent": "curl/8"}
PROXY = "https://gh-proxy.com/"
out = []


def p(*a):
    out.append(" ".join(str(x) for x in a))


# 1) nightly tag
try:
    r = requests.get(PROXY + "https://github.com/ggml-org/llama.cpp/releases/download/v0.9.0/nightly-tag.txt",
                     timeout=30, headers=UA)
    tag = r.text.strip()
    p("nightly-tag:", r.status_code, repr(tag[:40]))
    for asset in ("llama-{t}-bin-win-avx2-x64.zip", "llama-{t}-bin-win-cpu-x64.zip",
                  "llama-{t}-bin-win-cuda-x64.zip", "llama-{t}-bin-win-cuda-12.4-x64.zip"):
        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/" + asset.format(t=tag)
        try:
            h = requests.head(PROXY + url, allow_redirects=True, timeout=25, headers=UA)
            p(asset, h.status_code, h.headers.get("content-length"))
        except Exception as exc:
            p(asset, "ERR", str(exc)[:80])
except Exception as exc:
    p("nightly ERR", type(exc).__name__, str(exc)[:150])

# 2) torch / transformers
for mod in ("torch", "transformers", "onnxruntime_genai", "llama_cpp"):
    try:
        m = __import__(mod)
        p(f"{mod}: {getattr(m, '__version__', 'ok')}")
    except Exception as exc:
        p(f"{mod}: MISSING ({type(exc).__name__})")

# 3) ModelScope onnx LLM 候选
for repo, path in (("onnx-community/Qwen2.5-1.5B-Instruct", "model_int4.onnx"),
                   ("Qwen/Qwen2.5-1.5B-Instruct-onnx", "model.onnx"),
                   ("microsoft/Phi-3.5-mini-instruct-onnx", "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/model.onnx")):
    url = f"https://modelscope.cn/models/{repo}/resolve/master/{path}"
    try:
        h = requests.head(url, allow_redirects=True, timeout=20, headers=UA)
        p("ms", repo, h.status_code, h.headers.get("content-length"))
    except Exception as exc:
        p("ms", repo, "ERR", str(exc)[:80])

with open("tools/_probe4.out", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
print("ok")
