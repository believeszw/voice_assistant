"""探测 MiMo 语音接口（chat/completions 方言：ASR 与 TTS）。"""

import base64
import json
import re
from pathlib import Path

import requests

CFG = Path(r"C:\Users\Administrator\.dsh\.credentials.yaml")
BASE = "https://token-plan-cn.xiaomimimo.com/v1"
KEY = re.search(r"XIAOMI_API_KEY:\s*(\S+)", CFG.read_text(encoding="utf-8")).group(1)
H = {"Authorization": f"Bearer {KEY}"}


def asr(wav_path: Path) -> str:
    b64 = base64.b64encode(wav_path.read_bytes()).decode()
    body = {
        "model": "mimo-v2.5-asr",
        "messages": [{
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": {"data": f"data:audio/wav;base64,{b64}"},
            }],
        }],
        "asr_options": {"language": "zh"},
    }
    r = requests.post(f"{BASE}/chat/completions", headers=H, json=body, timeout=90)
    if r.status_code != 200:
        return f"[HTTP {r.status_code}] {r.text[:300]}"
    return r.json()["choices"][0]["message"]["content"]


def tts(text: str, out: Path) -> str:
    body = {
        "model": "mimo-v2.5-tts",
        "messages": [
            {"role": "user", "content": "语速稍快，语气自然"},
            {"role": "assistant", "content": text},
        ],
        "audio": {"voice": "冰糖", "format": "wav"},
    }
    r = requests.post(f"{BASE}/chat/completions", headers=H, json=body, timeout=120)
    print("TTS status:", r.status_code)
    if r.status_code != 200:
        return f"[HTTP {r.status_code}] {r.text[:400]}"
    data = r.json()
    msg = data["choices"][0]["message"]
    print("message keys:", list(msg.keys()))
    audio = msg.get("audio") or {}
    print("audio keys:", list(audio.keys()) if isinstance(audio, dict) else type(audio))
    b64 = audio.get("data") if isinstance(audio, dict) else None
    if not b64:
        return f"no audio data: {json.dumps(data)[:400]}"
    raw = base64.b64decode(b64)
    out.write_bytes(raw)
    return f"saved {out} {len(raw)} bytes head={raw[:4]}"


if __name__ == "__main__":
    wav = Path("tools/wav/case_4.wav")
    print("ASR case_4 (把音量调大一点):", asr(wav))
    for i in (1, 7):
        p = Path(f"tools/wav/case_{i}.wav")
        print(f"ASR case_{i}:", asr(p))
    print(tts("好的，音量已经调大了。", Path("tools/wav/mimo_tts.wav")))
