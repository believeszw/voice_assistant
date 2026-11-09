"""真实副作用自测：打开记事本、设置音量、截屏。

之前的 test_compound.py 用 dry_run 跑，只验证了解析和回复文本，
没验证「应用到底有没有真的打开」。这个脚本补上副作用断言。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions  # noqa: E402


def notepad_pids():
    return [p.pid for p in actions.psutil.process_iter(["name"])
            if (p.info.get("name") or "").lower().startswith("notepad")]


def check_open_notepad():
    actions.close_app("记事本")          # 清场
    time.sleep(0.5)
    ok, msg = actions.open_app("记事本")
    print(f"open_app: ok={ok} msg={msg!r}")
    deadline = time.time() + 3.0
    pids = []
    while time.time() < deadline:
        pids = notepad_pids()
        if pids:
            break
        time.sleep(0.15)
    print(f"notepad pids: {pids}")
    actions.close_app("记事本")
    return ok and bool(pids)


def check_volume():
    before = actions.get_volume()
    print(f"volume before: {before}")
    ok1, msg1 = actions.set_volume(30)
    time.sleep(0.4)
    v30 = actions.get_volume()
    ok2, msg2 = actions.set_volume(50)
    time.sleep(0.4)
    v50 = actions.get_volume()
    print(f"set_volume(30): {msg1!r} -> {v30}")
    print(f"set_volume(50): {msg2!r} -> {v50}")
    if before is not None:
        actions.set_volume(before)
    return ok1 and ok2 and v30 is not None and abs(v30 - 30) <= 3 and v50 is not None and abs(v50 - 50) <= 3


def check_screenshot():
    ok, msg = actions.screenshot()
    print(f"screenshot: ok={ok} msg={msg!r}")
    path = None
    if "保存在 " in msg:
        path = msg.split("保存在 ", 1)[1].strip()
    return ok and (path is None or os.path.exists(path))


def main():
    results = {}
    try:
        results["打开记事本（真实进程）"] = check_open_notepad()
    except Exception as exc:  # noqa: BLE001
        print(f"open_app 异常: {exc!r}")
        results["打开记事本（真实进程）"] = False
    results["设置音量（读回校验）"] = check_volume()
    results["截屏（文件落盘）"] = check_screenshot()

    print("\n===== 汇总 =====")
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    all_ok = all(results.values())
    print(f"\n{'PASS' if all_ok else 'FAIL'} (真实副作用自测)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
