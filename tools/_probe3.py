"""临时探测：llama.cpp 各 release 的 Windows 资产。跑完可删。"""
import json

import requests

UA = {"User-Agent": "curl/8"}
PROXY = "https://gh-proxy.com/"
out = []


def p(*a):
    out.append(" ".join(str(x) for x in a))


try:
    r = requests.get(PROXY + "https://api.github.com/repos/ggml-org/llama.cpp/releases",
                     params={"per_page": 8}, timeout=40, headers=UA)
    rels = r.json()
    p("status", r.status_code, "count", len(rels))
    for rel in rels:
        p("TAG", rel.get("tag_name"), "prerelease", rel.get("prerelease"), "assets", len(rel.get("assets") or []))
        names = [a["name"] for a in (rel.get("assets") or [])]
        wins = [n for n in names if "win" in n]
        p("   all:", names[:12])
        p("   win:", wins[:12])
except Exception as exc:
    p("ERR", type(exc).__name__, str(exc)[:300])

with open("tools/_probe3.out", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
print("ok")
