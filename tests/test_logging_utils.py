"""logging_utils 的行为约定：幂等、格式为纯消息、级别可配。"""

import logging

import pytest

import logging_utils


def _our_handlers():
    """只统计本项目挂的 handler（pytest 自己也会往 root 加 handler）。"""
    return [
        h
        for h in logging.getLogger().handlers
        if getattr(h, "formatter", None) is not None and getattr(h.formatter, "_fmt", None) == "%(message)s"
    ]


@pytest.fixture(autouse=True)
def _reset_logging_utils():
    """每个用例重置模块状态，避免 setup() 幂等影响其他用例。"""
    logging_utils._configured = False
    root = logging.getLogger()
    for h in _our_handlers():
        root.removeHandler(h)
    yield
    logging_utils._configured = False
    for h in _our_handlers():
        root.removeHandler(h)


def test_setup_is_idempotent():
    logging_utils.setup()
    assert len(_our_handlers()) == 1
    logging_utils.setup()
    assert len(_our_handlers()) == 1


def test_message_format_is_plain(capsys):
    logging_utils.setup()
    logging_utils.get_logger("voice_assistant.test").info("你好")
    captured = capsys.readouterr()
    assert captured.out.strip() == "你好"


def test_level_from_env(monkeypatch):
    monkeypatch.setenv("VA_LOG_LEVEL", "WARNING")
    logging_utils.setup()
    assert logging.getLogger().level == logging.WARNING


def test_get_logger_uses_name():
    logger = logging_utils.get_logger("voice_assistant.tts")
    assert logger.name == "voice_assistant.tts"
