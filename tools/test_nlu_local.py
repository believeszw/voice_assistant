"""端侧 NLU 验收：启动 llama-server，跑一组指令 + 长尾说法，输出意图与延迟。

用法（先确保 models/llm/*.gguf 与 tools/llama/llama-server.exe 就位）：
  C:\\va-venv\\Scripts\\python.exe tools\\test_nlu_local.py            # json_schema 约束解码
  set NLU_LOCAL_TOOL_CALLS=1 && C:\\va-venv\\Scripts\\python.exe tools\\test_nlu_local.py  # tool_calls
结果：tools/test_nlu_local.out（UTF-8）
"""
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import nlu_local  # noqa: E402

_MODE = "tool_calls" if nlu_local.config.NLU_LOCAL_TOOL_CALLS else "json_schema"
OUT = BASE / "tools" / f"test_nlu_local_{_MODE}.out"

CASES = [
    # (说法, 期望动作, 期望槽位)
    ("打开记事本", "open_app", {"name": "记事本"}),
    ("帮我把计算器打开", "open_app", {"name": "计算器"}),
    ("把音量调到三十", "volume_set", {"value": 30}),
    ("音量条到大点", "volume_up", None),
    ("声音小一点", "volume_down", None),
    ("静音", "mute", None),
    ("现在几点了", "time", None),
    ("今天几号", "date", None),
    ("截个屏", "screenshot", None),
    ("退出", "exit", None),
    ("讲个笑话", "chat", None),
    ("查一下明天天气", "search", {"term": None}),
    ("打开下载文件夹", "open_folder", {"name": "下载"}),
    ("打开哔哩哔哩", "open_app", {"name": "哔哩哔哩"}),
    # 长尾/口语句式（规则解析大概率 miss 的）
    ("我有点热你把空调给我开到二十四度", "unknown", None),
    ("那个麻烦帮我把声音关掉", "mute", None),
    ("把浏览器给我整出来", "open_app", None),
    ("现在这个点儿了", "time", None),
    ("给我来一段笑话吧", "chat", None),
    ("声音调到最大", "volume_max", None),
]


def main():
    lines = []
    t0 = time.time()
    warm = nlu_local._ensure_server()
    lines.append(f"server: {warm} start={time.time() - t0:.2f}s err={nlu_local.error()}")
    lines.append(f"mode: {'tool_calls' if nlu_local.config.NLU_LOCAL_TOOL_CALLS else 'json_schema'}")
    if not warm:
        OUT.write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines))
        return
    ok = 0
    lat = []
    for text, want_action, want_slots in CASES:
        t = time.time()
        intent = nlu_local.parse(text)
        ms = (time.time() - t) * 1000
        lat.append(ms)
        action = intent.get("action", "-")
        good = (want_action is None or action == want_action
                or (want_action == "unknown" and not intent))
        slot_ok = True
        if want_slots:
            for k, v in want_slots.items():
                if v is not None and intent.get(k) != v:
                    slot_ok = False
        if good and slot_ok:
            ok += 1
        lines.append(f"{'PASS' if good and slot_ok else 'FAIL'} {ms:6.0f}ms {text!r} -> "
                     f"{ {k: v for k, v in intent.items() if k != 'local'} }")
    lat.sort()
    lines.append("")
    lines.append(f"准确 {ok}/{len(CASES)}  P50={lat[len(lat) // 2]:.0f}ms  "
                 f"P95={lat[int(len(lat) * 0.95)]:.0f}ms  max={lat[-1]:.0f}ms")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    nlu_local.stop()


if __name__ == "__main__":
    main()
