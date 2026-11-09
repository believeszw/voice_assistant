"""临时探测：sherpa-onnx TTS API 字段 + llama.cpp Windows 资产名。跑完可删。"""
import dataclasses
import json

import requests
import sherpa_onnx

out = []


def p(*args):
    out.append(" ".join(str(a) for a in args))


for name in ("OfflineTtsVitsModelConfig", "OfflineTtsModelConfig", "OfflineTtsConfig"):
    cls = getattr(sherpa_onnx, name, None)
    if cls is None:
        p(name, "MISSING")
        continue
    try:
        fields = [f.name for f in dataclasses.fields(cls)]
    except Exception:
        fields = [a for a in dir(cls) if not a.startswith("_")]
    p(name, "fields:", fields)

p("\n== llama.cpp assets (v0.9.0) ==")
try:
    r = requests.get(
        "https://gh-proxy.com/https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
        timeout=30, headers={"User-Agent": "curl/8"})
    data = r.json()
    p("tag:", data.get("tag_name"))
    for a in data.get("assets", []):
        p("  ", a["name"], f"{a['size'] / 1e6:.0f}MB")
except Exception as exc:
    p("ERR", type(exc).__name__, str(exc)[:200])

with open("tools/_probe2.out", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
print("wrote tools/_probe2.out")
