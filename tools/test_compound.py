"""测试：一句话多个指令（复合指令）。

只看「解析 + 执行顺序 + 回复」，不碰真实设备：
把 actions 的动作函数替换成记录器，避免真的打开应用/改音量/截屏。
真实副作用由 tools/test_compound_real.py 验证。
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assistant as A  # noqa: E402
import actions as ACT  # noqa: E402


class DummySpeaker:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)

    def say_async(self, text):
        self.said.append(text)
        done = threading.Event()
        done.set()
        return done

    def say_quick(self, text):
        self.said.append(text)

    def pause(self):
        return True

    def resume(self):
        pass

    def discard(self):
        pass

    def stop(self):
        pass

    def playing(self):
        return False

    def shutdown(self):
        pass


CALLS = []


def fake(ok, fmt):
    def inner(*args, **kwargs):
        CALLS.append((fmt, args, kwargs))
        return True, fmt.format(*args)
    return inner


def patch_actions():
    ACT.open_app = fake(True, "已打开 {0}")
    ACT.close_app = fake(True, "已关闭 {0}")
    ACT.set_volume = lambda percent: (CALLS.append(("set_volume", percent)) or (True, f"音量已调到 {percent}%"))
    ACT.volume_step = lambda delta: (CALLS.append(("volume_step", delta)) or (True, f"音量已调整 {delta}%"))
    ACT.volume_max = lambda: (True, "音量已调到 100%")
    ACT.mute = lambda on=True: (True, "已静音" if on else "已取消静音")
    ACT.screenshot = lambda: (True, "已截屏，保存在 C:\\tmp\\shot.png")
    ACT.show_desktop = lambda: (True, "已显示桌面")
    ACT.tell_time = lambda: (True, "现在是 10 点 0 分")
    ACT.tell_date = lambda: (True, "今天是 1 月 1 日")
    ACT.media_play_pause = lambda: (True, "已播放或暂停")
    ACT.media_next = lambda: (True, "下一首")
    ACT.lock_screen = lambda: (True, "已锁屏")


CASES = [
    ("打开记事本，然后调大音量", ["已打开", "音量"]),
    ("静音，再显示桌面", ["静音", "桌面"]),
    ("现在几点了，然后截个屏", ["点", "截"]),
    ("音量调到三十，并且静音", ["30", "静音"]),
    # 用户实测暴露的第二句省略「音量」的说法
    ("把音量调到三十，然后再调到百分之五十", ["30", "50"]),
    ("打开记事本，然后调大音量到50%", ["已打开", "50"]),
    ("打开记事本", ["已打开"]),
]


def main():
    patch_actions()
    bot = A.Assistant(text_mode=True, dry_run=True, use_hotkey=False, use_wake=False)
    bot.speaker = DummySpeaker()
    fails = 0
    for text, keywords in CASES:
        CALLS.clear()
        bot.speaker.said.clear()
        reply, should_exit = bot.handle(text)
        print(f"\n输入: {text!r}")
        print(f"  回复: {reply!r}  exit={should_exit}  动作={CALLS}")
        joined = reply + "".join(bot.speaker.said)
        missing = [k for k in keywords if k not in joined]
        if missing:
            print(f"  FAIL 缺少关键字: {missing}")
            fails += 1
        else:
            print("  PASS")
    print("\n===== 汇总 =====")
    print("FAIL" if fails else "PASS", f"({len(CASES) - fails}/{len(CASES)} 通过)")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
