"""复合指令真副作用测试：真的执行动作，而不是 dry_run。

验证两件事（用户反馈的两个问题）：
1) 第二句「再调到百分之五十」必须真的执行，而不是只执行第一句；
2) 「打开记事本」必须真的出现记事本进程。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions  # noqa: E402
from assistant import Assistant  # noqa: E402


def notepad_pids():
    return [p.pid for p in actions.psutil.process_iter(["name"])
            if (p.info.get("name") or "").lower().startswith("notepad")]


def main():
    bot = Assistant(text_mode=True, dry_run=False, use_hotkey=False, use_wake=False)
    ok_all = True

    # --- 1. 音量复合：第一句 30，第二句 50，最后应该停在 50 ---
    actions.close_app("记事本")
    actions.set_volume(10)
    reply, _ = bot.handle("把音量调到三十，然后再调到百分之五十")
    time.sleep(0.5)
    v = actions.get_volume()
    print(f"回复: {reply!r}")
    print(f"最终音量: {v}（期望 50）")
    step1 = abs(v - 50) <= 3
    ok_all &= step1

    # --- 2. 打开记事本 + 调音量，两个动作都要落地 ---
    actions.close_app("记事本")
    time.sleep(0.4)
    reply, _ = bot.handle("打开记事本，然后调大音量到 50%")
    print(f"回复: {reply!r}")
    deadline = time.time() + 3.0
    pids = []
    while time.time() < deadline:
        pids = notepad_pids()
        if pids:
            break
        time.sleep(0.15)
    print(f"记事本进程: {pids}")
    actions.close_app("记事本")
    step2 = bool(pids)
    ok_all &= step2

    print("\n===== 汇总 =====")
    print(f"{'PASS' if step1 else 'FAIL'}  复合音量：第一句 30 → 第二句 50")
    print(f"{'PASS' if step2 else 'FAIL'}  复合打开应用：记事本真实启动")
    print(f"\n{'PASS' if ok_all else 'FAIL'} (复合指令真副作用)")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
