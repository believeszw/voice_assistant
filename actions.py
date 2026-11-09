"""电脑操作集合：每个函数返回 (ok, 回复文本)。"""

import ctypes
import datetime
import os
import re
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

import psutil

from config import APPS, BROWSER_PATHS, FOLDERS, SEARCH_BROWSER

user32 = ctypes.windll.user32

# ---- 虚拟键码 ----
VK = {
    "vol_mute": 0xAD, "vol_down": 0xAE, "vol_up": 0xAF,
    "media_next": 0xB0, "media_prev": 0xB1, "media_stop": 0xB2,
    "media_play": 0xB3, "win": 0x5B, "d": 0x44,
    "ctrl": 0x11, "v": 0x56, "esc": 0x1B, "alt": 0x12, "f4": 0x73,
}
KEYEVENTF_KEYUP = 0x0002

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _press(vk: int, times: int = 1, hold: float = 0.03):
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(hold)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)


def _combo(*vks):
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)


# ---------------- 音量 ----------------
def _default_device():
    import comtypes
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers()


def _endpoint():
    return _default_device().EndpointVolume


def get_volume():
    try:
        return int(round(_default_device().volume_percent))
    except Exception:
        try:
            return int(round(_endpoint().GetMasterVolumeLevelScalar() * 100))
        except Exception:
            return None


def set_volume(percent: int):
    percent = max(0, min(100, int(percent)))
    try:
        _endpoint().SetMasterVolumeLevelScalar(percent / 100.0, None)
        return True, f"音量已调到 {percent}%"
    except Exception:
        # 退化方案：用按键一步步靠近（只能近似）
        _press(VK["vol_up"], 50)
        return True, f"音量已调到 {percent}%（当前设备不支持精确设置）"


def volume_step(delta: int):
    """delta>0 增大（每次 5%），<0 减小。"""
    cur = get_volume()
    if cur is None:
        _press(VK["vol_up"] if delta > 0 else VK["vol_down"], 4)
        return True, "音量已调大" if delta > 0 else "音量已调小"
    target = max(0, min(100, cur + delta))
    ok, _ = set_volume(target)
    return ok, f"音量{'调大' if delta > 0 else '调小'}到 {target}%"


def mute(on: bool = True):
    try:
        _endpoint().SetMute(1 if on else 0, None)
        return True, "已静音" if on else "已取消静音"
    except Exception:
        _press(VK["vol_mute"])
        return True, "已静音" if on else "已取消静音"


def volume_max():
    return set_volume(100)


# ---------------- 媒体 ----------------
def media_play_pause():
    _press(VK["media_play"])
    return True, "已播放或暂停"


def media_next():
    _press(VK["media_next"])
    return True, "下一首"


def media_prev():
    _press(VK["media_prev"])
    return True, "上一首"


# ---------------- 应用 ----------------
def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "")


_NORMALIZED_APPS = {_normalize_name(k): v for k, v in APPS.items()}


def resolve_app(name: str):
    key = _normalize_name(name)
    target = _NORMALIZED_APPS.get(key)
    if target is None:
        for k, v in _NORMALIZED_APPS.items():
            if k in key or key in k:
                target = v
                break
    if target in ("chrome", "msedge", "chrome.exe", "msedge.exe"):
        exe = _browser_exe("chrome" if "chrome" in target else "edge")
        if exe:
            return exe
    return target


def _foreground_exe() -> str:
    """当前前台窗口对应进程名（小写）；用于判断「应用是否真的被带到前台」。"""
    try:
        import ctypes
        import ctypes.wintypes as wt

        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        for p in psutil.process_iter(["pid", "name"]):
            if p.info.get("pid") == pid.value:
                return (p.info.get("name") or "").lower()
    except Exception:
        pass
    return ""


_last_verify = {}


def _verify_open(exe: str, before: set, timeout: float = 2.5) -> bool:
    """成功判据：该应用被切到前台，或出现可见、非最小化、有标题的窗口。"""
    exe_l = exe.lower()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _foreground_exe() == exe_l:
            _last_verify.update(fg=exe_l, visible=True, new_pids=len(_running_pids(exe) - before))
            return True
        if _has_visible_window(exe):
            _last_verify.update(fg=_foreground_exe(), visible=True, new_pids=len(_running_pids(exe) - before))
            return True
        time.sleep(0.15)
    _last_verify.update(fg=_foreground_exe(), visible=_has_visible_window(exe),
                        new_pids=len(_running_pids(exe) - before))
    return False


def _running_pids(exe: str):
    exe = exe.lower()
    pids = set()
    for p in psutil.process_iter(["name"]):
        if (p.info.get("name") or "").lower() == exe:
            pids.add(p.pid)
    return pids


def _wait_new_process(exe: str, before: set, timeout: float = 2.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _running_pids(exe) - before:
            return True
        time.sleep(0.15)
    return False


def _bring_to_front(exe: str) -> bool:
    """把已在运行的应用窗口恢复并切到前台（最小化/被遮挡时用）。"""
    try:
        import win32con
        import win32gui
        import win32process
    except Exception:
        return False
    hwnds = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            name = psutil.Process(pid).name().lower()
        except Exception:
            return
        if name == exe.lower():
            hwnds.append(hwnd)

    try:
        win32gui.EnumWindows(_cb, None)
        if not hwnds:
            return False
        hwnd = hwnds[0]
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _has_visible_window(exe: str) -> bool:
    """该进程是否存在可见、非最小化、有标题的窗口（fail-closed）。"""
    try:
        import win32gui
        import win32process
    except Exception:
        return False
    found = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return
        if not win32gui.GetWindowText(hwnd):
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            name = psutil.Process(pid).name().lower()
        except Exception:
            return
        if name == exe.lower():
            found.append(hwnd)

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return False
    return bool(found)


# 允许的启动目标字符：字母数字、常见路径符号、中文；拦掉 cmd 元字符（& | > < ^ % 等）
_SAFE_TARGET = re.compile(r"^[A-Za-z0-9_\-./:\\ \u4e00-\u9fff]{1,80}$")


def open_app(name: str):
    target = resolve_app(name)
    if target is None:
        # 不在别名表里，直接交给 start 试一次（先做字符白名单，避免 ASR 文本被当成命令）
        target = name.strip()
        if not _SAFE_TARGET.match(target):
            return False, f"这个应用名我不能直接启动：{name}"
    if target.startswith("http"):
        webbrowser.open(target)
        return True, f"已打开 {name}"
    if target.endswith(":"):
        try:
            os.startfile(target)
            return True, f"已打开 {name}"
        except OSError as exc:
            return False, f"没能打开 {name}：{exc}"

    exe = os.path.basename(target)
    if not exe.lower().endswith(".exe"):
        exe += ".exe"
    before = _running_pids(exe)
    if before and _bring_to_front(exe):
        if _verify_open(exe, before, timeout=1.0):
            return True, f"已打开 {name}"
    try:
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return False, f"没能打开 {name}：{exc}"
    if _verify_open(exe, before):
        fg = _foreground_exe()
        if fg and fg != exe.lower():
            _bring_to_front(exe)
            fg = _foreground_exe()
            if fg != exe.lower():
                return True, f"已打开 {name}（但前台是 {fg}，窗口被挡住）"
        return True, f"已打开 {name}"
    # 备用方案：os.startfile（对带空格的完整路径更稳）
    try:
        os.startfile(target)
    except OSError:
        pass
    if _verify_open(exe, before):
        return True, f"已打开 {name}"
    if before and _bring_to_front(exe):
        if _verify_open(exe, before, timeout=1.0):
            return True, f"已打开 {name}"
    diag = f"新进程 {_last_verify.get('new_pids')}，可见窗口 {_last_verify.get('visible')}，前台 {_last_verify.get('fg')}"
    if before:
        return False, f"{name} 已在运行，但没能切到前台（{diag}）"
    return False, f"没能打开 {name}（{diag}）"


def close_app(name: str):
    target = resolve_app(name)
    if target is None or target.startswith("http") or target.endswith(":"):
        return False, f"我不知道怎么关闭 {name}"
    exe = target if target.lower().endswith(".exe") else target + ".exe"
    proc = subprocess.run(["taskkill", "/IM", exe, "/F"],
                          capture_output=True, text=True)
    if proc.returncode == 0:
        return True, f"已关闭 {name}"
    return False, f"没找到正在运行的 {name}"


# ---------------- 截屏 ----------------
def screenshot():
    from PIL import ImageGrab
    img = None
    candidates = [
        Path.home() / "Pictures" / "Screenshots",
        Path.home() / "Pictures",
        Path(__file__).resolve().parent / "screenshots",
    ]
    last_err = None
    for pic_dir in candidates:
        try:
            pic_dir.mkdir(parents=True, exist_ok=True)
            path = pic_dir / time.strftime("shot_%Y%m%d_%H%M%S.png")
            img = ImageGrab.grab(all_screens=True)
            img.save(path)
            return True, f"已截屏，保存在 {path}"
        except (PermissionError, OSError) as e:
            last_err = e
            continue
    return False, f"截屏失败：{last_err}"


# ---------------- 系统 ----------------
def lock_screen():
    user32.LockWorkStation()
    return True, "已锁屏"


def sleep_pc():
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return True, "电脑进入睡眠"


def shutdown_pc(delay: int = 20):
    subprocess.run(["shutdown", "/s", "/t", str(delay)], capture_output=True)
    return True, f"{delay} 秒后关机，说“取消关机”可以撤销"


def restart_pc(delay: int = 20):
    subprocess.run(["shutdown", "/r", "/t", str(delay)], capture_output=True)
    return True, f"{delay} 秒后重启，说“取消关机”可以撤销"


def cancel_shutdown():
    proc = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
    if proc.returncode == 0:
        return True, "已取消关机"
    return False, "当前没有待执行的关机"


# ---------------- 网络 ----------------
def _browser_exe(name: str):
    """返回浏览器可执行文件路径；找不到返回 None。"""
    name = (name or "").lower()
    for key, paths in BROWSER_PATHS.items():
        if key in name:
            for path in paths:
                if os.path.exists(path):
                    return path
    return None


def _open_url(url: str, browser: str = ""):
    """优先用指定浏览器新标签页打开；失败退系统默认浏览器。返回 (ok, 浏览器名)。"""
    want = browser or SEARCH_BROWSER
    exe = _browser_exe(want)
    if exe:
        try:
            subprocess.Popen(
                [exe, "--new-tab", url], shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True, "Chrome" if "chrome" in exe.lower() else "Edge"
        except OSError:
            pass
    try:
        if webbrowser.open(url):
            return True, "默认浏览器"
    except Exception:
        pass
    return False, ""


def search_web(term: str, browser: str = ""):
    term = term.strip()
    if not term:
        return False, "要搜什么？"
    ok, who = _open_url("https://www.baidu.com/s?wd=" + quote(term), browser)
    return (True, f"已用{who}搜索 {term}") if ok else (False, "浏览器没打开成功")


def open_url(url: str, browser: str = ""):
    ok, who = _open_url(url, browser)
    return (True, f"已用{who}打开网页") if ok else (False, "浏览器没打开成功")


# ---------------- 查询 ----------------
def tell_time():
    now = datetime.datetime.now()
    return True, f"现在是 {now.hour} 点 {now.minute} 分"


def tell_date():
    now = datetime.datetime.now()
    return True, f"今天是 {now.year} 年 {now.month} 月 {now.day} 日，{WEEKDAYS[now.weekday()]}"


def system_info():
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.3)
    parts = [f"CPU {cpu:.0f}%", f"内存 {mem.percent:.0f}%"]
    battery = psutil.sensors_battery()
    if battery is not None:
        parts.append(f"电量 {battery.percent:.0f}%")
    disk = psutil.disk_usage("C:/")
    parts.append(f"C 盘剩余 {disk.free / 1024 ** 3:.0f} G")
    return True, "，".join(parts)


# ---------------- 剪贴板 / 输入 ----------------
def copy_text(text: str):
    import pyperclip
    if not text:
        return False, "要复制什么？"
    pyperclip.copy(text)
    return True, "已复制到剪贴板"


def read_clipboard():
    import pyperclip
    text = pyperclip.paste()
    if not text:
        return True, "剪贴板是空的"
    return True, "剪贴板内容是：" + text[:200]


def type_text(text: str):
    import pyperclip
    if not text:
        return False, "要输入什么？"
    pyperclip.copy(text)
    time.sleep(0.15)
    _combo(VK["ctrl"], VK["v"])
    return True, "已输入"


def show_desktop():
    _combo(VK["win"], VK["d"])
    return True, "已显示桌面"


# ---------------- 文件夹 / 文件 ----------------
def _launch_path(path: Path) -> bool:
    """打开文件夹或文件：先试 shell 关联，失败退 explorer（提权进程上 startfile 常报 WinError 5）。"""
    try:
        os.startfile(str(path))
        return True
    except OSError:
        pass
    try:
        subprocess.Popen(
            ["explorer", str(path)], shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.2)
        return True
    except OSError:
        return False


def _folder_path(name: str):
    for key, folder in FOLDERS.items():
        if key in name:
            path = Path.home() / folder
            return key, path if path.is_dir() else None
    return name, None


def open_folder(name: str):
    key, path = _folder_path(name)
    if path is None:
        return False, f"找不到{key}文件夹"
    if _launch_path(path):
        return True, f"已打开{key}"
    return False, f"没权限打开{key}文件夹"


_SUFFIXES = ("", ".txt", ".md", ".doc", ".docx", ".pdf", ".xls", ".xlsx",
             ".ppt", ".pptx", ".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mp3")


def open_item(folder: str, name: str):
    """打开某个文件夹下的指定文件，例如「打开桌面的新建文本」。"""
    key, base = _folder_path(folder)
    if base is None:
        return False, f"找不到{key}文件夹"
    name = name.strip().strip("。.!！?？ ")
    if not name:
        return open_folder(folder)
    files = [p for p in base.iterdir() if p.is_file() or p.is_dir()]
    lower = name.lower()
    hits = [p for p in files if p.stem.lower() == lower]
    hits += [p for p in files if p.stem.lower().startswith(lower)]
    hits += [p for p in files if lower in p.stem.lower()]
    for suffix in _SUFFIXES:
        cand = base / (name + suffix)
        if cand.exists() and cand not in hits:
            hits.append(cand)
    if not hits:
        hint = "、".join(p.name for p in files[:6])
        return False, f"{key}上没找到「{name}」" + (f"，有：{hint}" if hint else "")
    target = hits[0]
    if _launch_path(target):
        return True, f"已打开{key}的「{target.stem}」"
    return False, f"没权限打开「{target.name}」"


# ---------------- 亮度 ----------------
def brightness(delta: int):
    ps = (
        "$b=(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness);"
        "$cur=$b.CurrentBrightness;"
        f"$new=[Math]::Max(0,[Math]::Min(100,$cur+({delta})));"
        "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
        ".WmiSetBrightness(1,$new);$new"
    )
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                          capture_output=True, text=True, timeout=15)
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and out:
        return True, f"亮度调到 {out}"
    return False, "这台机器的屏幕不支持调亮度"
