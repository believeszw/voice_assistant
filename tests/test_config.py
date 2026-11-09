"""config 的纯常量约定（不依赖声卡/网络，可在 CI 里跑）。"""

import config


def test_dangerous_actions_are_listed():
    # 危险动作必须显式登记，execute 会按这个集合走二次确认
    assert {"shutdown", "restart", "sleep", "close_app", "lock"} <= config.DANGEROUS


def test_audio_defaults():
    assert config.SAMPLE_RATE == 16000
    assert config.BLOCK_MS > 0
    assert config.COMMAND_MAX_SECONDS > config.COMMAND_SILENCE_SECONDS > 0


def test_session_limits_are_positive():
    assert config.SESSION_MAX_TURNS >= 1
    assert config.FOLLOWUP_START_TIMEOUT > 0


def test_wake_words_are_non_empty_strings():
    assert config.WAKE_WORDS
    assert all(isinstance(w, str) and w.strip() for w in config.WAKE_WORDS)


def test_browser_paths_have_known_keys():
    assert config.SEARCH_BROWSER in {"chrome", "edge", "default"}
    assert {"chrome", "edge"} <= set(config.BROWSER_PATHS)
