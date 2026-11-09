"""统一控制台日志。

用法::

    from logging_utils import get_logger
    log = get_logger(__name__)
    log.info("...")

控制台只输出消息本身（与旧 ``print`` 输出保持一致，方便工具按文本 grep）；
级别可用环境变量 ``VA_LOG_LEVEL`` 覆盖（默认 INFO）。
"""

from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(message)s"
_configured = False


def setup(level: str | None = None) -> None:
    """配置根 logger；幂等，可被多个模块/入口重复调用。"""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel((level or os.environ.get("VA_LOG_LEVEL", "INFO")).upper())
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """返回带统一控制台 handler 的 logger。"""
    setup()
    return logging.getLogger(name)
