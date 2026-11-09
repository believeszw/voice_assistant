"""临时诊断：按真实路径启动 assistant，定时 dump 所有线程栈，看卡在哪。"""
import faulthandler
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

faulthandler.dump_traceback_later(6, repeat=True)
sys.argv = ["assistant.py", "--no-hotkey"]
import assistant  # noqa: E402

assistant.main()
