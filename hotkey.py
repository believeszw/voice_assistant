"""全局热键：Ctrl+Alt+Space 唤醒，Ctrl+Alt+X 停止朗读。"""

import ctypes
import ctypes.wintypes
import threading

from logging_utils import get_logger

_logger = get_logger("voice_assistant.hotkey")

user32 = ctypes.windll.user32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_SPACE = 0x20
VK_X = 0x58


class Hotkeys:
    def __init__(self):
        self.wake = threading.Event()
        self.stop = threading.Event()
        self._thread = None
        self._ok = False

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        try:
            ok1 = user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE)
            ok2 = user32.RegisterHotKey(None, 2, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_X)
            self._ok = bool(ok1 and ok2)
            if not self._ok:
                _logger.warning("[热键] 注册失败（可能被其他程序占用），可用文字模式或唤醒词")
                return
            _logger.info("[热键] Ctrl+Alt+Space 唤醒 / Ctrl+Alt+X 停止朗读")
            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    if msg.wParam == 1:
                        self.wake.set()
                    elif msg.wParam == 2:
                        self.stop.set()
        except Exception as exc:  # pragma: no cover
            _logger.warning("[热键] 异常:", exc)

    def stop_listening(self):
        user32.UnregisterHotKey(None, 1)
        user32.UnregisterHotKey(None, 2)
        tid = self._thread.ident if self._thread else None
        if tid:
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
