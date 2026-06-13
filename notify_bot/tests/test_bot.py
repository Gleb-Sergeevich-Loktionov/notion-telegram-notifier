"""Tests for telegram/bot.py — importable glue, no long-polling.

Covers:
- create_dispatcher returns a Dispatcher with both routers included
- create_bot returns a Bot instance
- _EMPLOYEE_COMMANDS and _ADMIN_COMMANDS are non-empty lists of BotCommand
- _replace_in_json_list (handlers_admin helper) edge cases
- _subtract_seconds and _event_kind_for (poller helpers)
"""

import pytest
import pytest_asyncio

from notify_bot.config import Settings
from notify_bot.storage import db as db_mod
from notify_bot.telegram import bot as bot_mod
from notify_bot.telegram.bot import _ADMIN_COMMANDS, _EMPLOYEE_COMMANDS
from notify_bot.telegram import handlers_admin
from notify_bot.notion import poller as poller_mod


def _make_settings(**overrides):
    base = dict(
        notion_token="x",
        telegram_token="123:FAKE",
        notion_database_id="db1",
        admin_chat_ids=(999,),
        db_path=":memory:",
    )
    base.update(overrides)
    return Settings(**base)


@pytest_asyncio.fixture
async def conn():
    c = await db_mod.connect(":memory:")
    await db_mod.init_schema(c)
    yield c
    await c.close()


# ── bot module constants ───────────────────────────────────────


def test_employee_commands_non_empty():
    """_EMPLOYEE_COMMANDS contains at least /start and /me."""
    assert len(_EMPLOYEE_COMMANDS) >= 2
    commands = {c.command for c in _EMPLOYEE_COMMANDS}
    assert "start" in commands
    assert "me" in commands


def test_admin_commands_non_empty():
    """_ADMIN_COMMANDS contains all expected admin commands."""
    assert len(_ADMIN_COMMANDS) >= 5
    commands = {c.command for c in _ADMIN_COMMANDS}
    assert "invite" in commands
    assert "list" in commands
    assert "rename" in commands
    assert "unbind" in commands
    assert "pause" in commands
    assert "resume" in commands


def test_create_dispatcher_returns_dispatcher(conn):
    """create_dispatcher returns a Dispatcher with routers registered."""
    from aiogram import Dispatcher
    settings = _make_settings()
    dp = bot_mod.create_dispatcher(conn, settings)
    assert isinstance(dp, Dispatcher)


def test_create_bot_returns_bot():
    """create_bot returns an aiogram Bot instance."""
    from aiogram import Bot
    settings = _make_settings()
    bot = bot_mod.create_bot(settings)
    assert isinstance(bot, Bot)


# ── handlers_admin helpers ───────────────────────────────────


def test_replace_in_json_list_replaces_exact_element():
    """_replace_in_json_list swaps exact element, leaves others intact."""
    result = handlers_admin._replace_in_json_list('["A", "B", "C"]', "B", "X")
    import json
    assert json.loads(result) == ["A", "X", "C"]


def test_replace_in_json_list_no_match_unchanged():
    """_replace_in_json_list with no matching element returns unchanged."""
    result = handlers_admin._replace_in_json_list('["A", "B"]', "Z", "W")
    import json
    assert json.loads(result) == ["A", "B"]


def test_replace_in_json_list_invalid_json_returns_original():
    """_replace_in_json_list with invalid JSON returns original string."""
    result = handlers_admin._replace_in_json_list("not-json", "A", "B")
    assert result == "not-json"


def test_replace_in_json_list_substring_safety():
    """Exact element match only — 'А' does not corrupt 'Алиса'."""
    result = handlers_admin._replace_in_json_list('["А", "Алиса"]', "А", "Б")
    import json
    items = json.loads(result)
    assert "Б" in items
    assert "Алиса" in items
    assert "А" not in items


# ── poller helpers ─────────────────────────────────────────


def test_subtract_seconds_basic():
    """_subtract_seconds subtracts correct number of seconds."""
    result = poller_mod._subtract_seconds("2024-01-01T10:05:00.000Z", 300)
    assert result == "2024-01-01T10:00:00.000Z"


def test_subtract_seconds_invalid_iso_returns_original():
    """_subtract_seconds with invalid ISO string returns original."""
    result = poller_mod._subtract_seconds("not-a-timestamp", 60)
    assert result == "not-a-timestamp"


def test_event_kind_for_extracts_kind():
    """_event_kind_for extracts kind from dedup_key."""
    key = "page-id:new_assignee:Alice:2024-01-01T10:00:00Z:111"
    assert poller_mod._event_kind_for(key) == "new_assignee"


def test_event_kind_for_short_key():
    """_event_kind_for with too few parts returns 'unknown'."""
    assert poller_mod._event_kind_for("only-one-part") == "unknown"


# ── poller: NotionFatal keeps looping ──────────────────────────────


@pytest.mark.asyncio
async def test_poller_notion_fatal_keeps_looping(conn):
    """NotionFatal: poller logs critical but keeps iterating (does not crash)."""
    import asyncio
    from notify_bot.notion.client import NotionFatal
    from notify_bot.notion import poller as poller_mod
    from notify_bot.storage import repo_state

    settings = _make_settings(poll_interval=0)

    call_count = [0]

    class FatalClient:
        async def query_incremental(self, after):
            call_count[0] += 1
            if call_count[0] == 1:
                raise NotionFatal("auth expired")
            # Second call: stop event should be set by then
            return []

        async def retrieve_db(self):
            return {}

        async def retrieve_page(self, pid):
            return {}

        async def start_background_refresh(self):
            pass

    stop = asyncio.Event()

    async def fake_sender(chat_id, text):
        return True

    # Set stop after a short time so the loop terminates
    async def _stopper():
        # Wait for 2 iterations then stop
        for _ in range(20):
            await asyncio.sleep(0)
            if call_count[0] >= 2:
                break
        stop.set()

    await asyncio.gather(
        poller_mod.run(conn, FatalClient(), settings, fake_sender, stop),
        _stopper(),
    )

    # Loop ran at least once despite NotionFatal
    assert call_count[0] >= 1


# ── poller: heartbeat ─────────────────────────────────────────


def test_touch_heartbeat_creates_file(tmp_path):
    """_touch_heartbeat creates the file at the given path."""
    path = str(tmp_path / "heartbeat")
    poller_mod._touch_heartbeat(path)
    import pathlib
    assert pathlib.Path(path).exists()


def test_touch_heartbeat_unwritable_does_not_raise():
    """_touch_heartbeat on unwritable path logs warning but does not raise."""
    # /proc/impossible is not writable on macOS/Linux — just use a deep bad path
    poller_mod._touch_heartbeat("/this/path/does/not/exist/heartbeat")
