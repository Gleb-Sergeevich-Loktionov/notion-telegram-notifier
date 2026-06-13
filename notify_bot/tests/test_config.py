"""Tests for config.py load() function.

Covers:
- Happy path with all required env vars
- Missing required var → SystemExit with name in message
- Default values applied when optional vars absent
- ADMIN_CHAT_IDS parsing: "1,2 ,3" → (1, 2, 3)
- ADMIN_CHAT_IDS non-integer → SystemExit
- POLL_INTERVAL invalid int → SystemExit
- _opt falls back to default when value is whitespace-only
"""

import os
import sys
import pytest

import notify_bot.config as cfg_mod


def _base_env():
    return {
        "NOTION_TOKEN": "secret-notion",
        "TELEGRAM_TOKEN": "123:FAKE",
        "NOTION_DATABASE_ID": "db-abc",
        "ADMIN_CHAT_IDS": "999",
    }


def test_load_happy_path(monkeypatch):
    """All required vars present → Settings populated correctly."""
    env = _base_env()
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = cfg_mod.load()

    assert settings.notion_token == "secret-notion"
    assert settings.telegram_token == "123:FAKE"
    assert settings.notion_database_id == "db-abc"
    assert settings.admin_chat_ids == (999,)


def test_load_defaults_applied(monkeypatch):
    """Optional vars absent → defaults used."""
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    # Ensure optional vars are absent
    for opt in ["DB_PATH", "POLL_INTERVAL", "OVERLAP_SECONDS", "DISPLAY_TZ",
                "PROP_TITLE", "PROP_ASSIGNEE", "PROP_REPORTER", "PROP_STATUS",
                "PROP_PROJECT", "PROP_DUE", "DONE_STATUS"]:
        monkeypatch.delenv(opt, raising=False)

    settings = cfg_mod.load()

    assert settings.db_path == "/data/bot.db"
    assert settings.poll_interval == 90
    assert settings.overlap_seconds == 300
    assert settings.display_tz == "Europe/Moscow"
    assert settings.prop_title == "Name"
    assert settings.done_status == "Готово"


def test_load_missing_notion_token_exits(monkeypatch):
    """Missing NOTION_TOKEN → SystemExit."""
    env = _base_env()
    env.pop("NOTION_TOKEN")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("NOTION_TOKEN", raising=False)

    with pytest.raises(SystemExit):
        cfg_mod.load()


def test_load_missing_telegram_token_exits(monkeypatch):
    """Missing TELEGRAM_TOKEN → SystemExit."""
    env = _base_env()
    env.pop("TELEGRAM_TOKEN")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)

    with pytest.raises(SystemExit):
        cfg_mod.load()


def test_load_missing_database_id_exits(monkeypatch):
    """Missing NOTION_DATABASE_ID → SystemExit."""
    env = _base_env()
    env.pop("NOTION_DATABASE_ID")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)

    with pytest.raises(SystemExit):
        cfg_mod.load()


def test_load_missing_admin_chat_ids_exits(monkeypatch):
    """Missing ADMIN_CHAT_IDS → SystemExit."""
    env = _base_env()
    env.pop("ADMIN_CHAT_IDS")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ADMIN_CHAT_IDS", raising=False)

    with pytest.raises(SystemExit):
        cfg_mod.load()


def test_admin_chat_ids_multi_with_spaces(monkeypatch):
    """ADMIN_CHAT_IDS='1,2 ,3' → (1, 2, 3)."""
    env = _base_env()
    env["ADMIN_CHAT_IDS"] = "1,2 ,3"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = cfg_mod.load()
    assert settings.admin_chat_ids == (1, 2, 3)


def test_admin_chat_ids_non_integer_exits(monkeypatch):
    """ADMIN_CHAT_IDS with non-integer value → SystemExit."""
    env = _base_env()
    env["ADMIN_CHAT_IDS"] = "123,abc"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    with pytest.raises(SystemExit):
        cfg_mod.load()


def test_poll_interval_invalid_exits(monkeypatch):
    """POLL_INTERVAL='not_a_number' → SystemExit."""
    env = _base_env()
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("POLL_INTERVAL", "not_a_number")

    with pytest.raises(SystemExit):
        cfg_mod.load()


def test_poll_interval_custom(monkeypatch):
    """POLL_INTERVAL='60' → poll_interval=60."""
    env = _base_env()
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("POLL_INTERVAL", "60")

    settings = cfg_mod.load()
    assert settings.poll_interval == 60


def test_opt_whitespace_falls_back_to_default(monkeypatch):
    """_opt with whitespace-only value returns the default."""
    env = _base_env()
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DISPLAY_TZ", "   ")  # whitespace only

    settings = cfg_mod.load()
    assert settings.display_tz == "Europe/Moscow"


def test_props_config_property(monkeypatch):
    """Settings.props_config returns dict with all 6 keys."""
    env = _base_env()
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = cfg_mod.load()
    pc = settings.props_config
    assert set(pc.keys()) == {"title", "assignee", "reporter", "status", "project", "due"}
    assert pc["title"] == "Name"
    assert pc["assignee"] == "Assign_new"
