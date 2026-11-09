"""云端能力自测：ASR 准确率、意图理解、闲聊、TTS。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm  # noqa: E402

WAV = Path(__file__).resolve().parent / "wav"

CASES = [
    ("case_0.wav", "小助手"),
    ("case_1.wav", "小助手打开记事本"),
    ("case_2.wav", "打开记事本"),
    ("case_3.wav", "现在几点了"),
    ("case_4.wav", "把音量调大一点"),
    ("case_5.wav", "下一首"),
    ("case_6.wav", "截个屏"),
    ("case_7.wav", "关闭计算器"),
    ("case_8.wav", "音量调到五十"),
    ("case_9.wav", "搜索天气"),
    ("case_10.wav", "显示桌面"),
    ("case_11.wav", "锁屏"),
]

INTENTS = [
    "浪大",
    "老大",
    "两条大",
    "把音量调大一点",
    "声音小一点",
    "今天吃啥",
    "你叫什么名字",
    "打开记事本",
    "现在几点",
    "放首歌",
    "关闭计算器",
    "查一下明天上海天气",
    "讲个笑话",
    "小助手你好",
    "帮我把音量调到三十",
    "截个屏",
    "内存还剩多少",
    "退出",
]


def main():
    print("== 1. MiMo ASR ==")
    t0 = time.time()
    for fname, expect in CASES:
        path = WAV / fname
        if not path.exists():
            print(f"{fname}: 缺文件")
            continue
        try:
            got = llm.asr_wav(path.read_bytes())
        except Exception as exc:
            got = f"[ERR] {exc}"
        mark = "OK " if expect in got or got in expect else "?? "
        print(f"{mark}{fname:<12} 期望={expect!r:<16} 识别={got!r}")
    print(f"ASR 总耗时 {time.time()-t0:.1f}s")

    print("\n== 2. LLM 意图理解 ==")
    for text in INTENTS:
        try:
            intent = llm.understand(text)
        except Exception as exc:
            intent = {"action": f"[ERR] {exc}"}
        print(f"{text!r:<24} -> {intent}")

    print("\n== 3. 闲聊 ==")
    for text in ["今天吃啥", "你叫什么名字", "讲个笑话"]:
        t0 = time.time()
        try:
            reply = llm.chat_reply(text)
        except Exception as exc:
            reply = f"[ERR] {exc}"
        print(f"{text!r}: {reply!r}  ({time.time()-t0:.1f}s)")

    print("\n== 4. TTS ==")
    t0 = time.time()
    try:
        wav = llm.tts_wav("好的，音量已经调大了。")
        out = WAV / "mimo_tts_test.wav"
        out.write_bytes(wav)
        print(f"合成 {len(wav)} 字节 -> {out} （{time.time()-t0:.1f}s）")
    except Exception as exc:
        print(f"TTS 失败: {exc}")


if __name__ == "__main__":
    main()
