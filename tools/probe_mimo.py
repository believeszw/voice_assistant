"""探测 MiMo 平台：chat / ASR / TTS 三个接口是否可用。仅调试用。"""

import base64
import json
import re
import urllib.request
from pathlib import Path

import requests

CFG = Path(r"C:\Users\Administrator\.dsh\.credentials.yaml")
BASE = "https://token-plan-cn.xiaomimimo.com/v1"
key = re.search(r"XIAOMI_API_KEY:\s*(\S+)", CFG.read_text(encoding="utf-8")).group(1)
H = {"Authorization": f"Bearer {key}"}

print("=== chat ===")
r = requests.post(f"{BASE}/chat/completions", headers=H, json={
    "model": "mimo-v2.6-flash",
    "messages": [{"role": "user", "content": "用一句话回答：你好"}],
    "max_tokens": 50,
}, timeout=60)
print(r.status_code, r.text[:400])

print("\n=== asr ===")
wav = Path("tools/wav/case_4.wav")
print("wav:", wav, wav.stat().st_size if wav.exists() else "missing")
with open(wav, "rb") as f:
    r = requests.post(f"{BASE}/audio/transcriptions", headers=H,
                      files={"file": ("a.wav", f, "audio/wav")},
                      data={"model": "mimo-v2.5-asr"}, timeout=90)
print(r.status_code, r.text[:500])

print("\n=== tts ===")
r = requests.post(f"{BASE}/audio/speech", headers=H, json={
    "model": "mimo-v2.5-tts",
    "input": "你好，我是你的语音助手。",
    "voice": "alloy",
}, timeout=90)
print(r.status_code, r.headers.get("content-type"), len(r.content))
if r.status_code == 200:
    Path("tools/wav/tts_probe.bin").write_bytes(r.content)
    print("saved tools/wav/tts_probe.bin", r.content[:4])
