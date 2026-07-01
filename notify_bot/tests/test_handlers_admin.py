"""Tests for telegram/handlers_admin.py — direct handler invocation.

Extends existing test_admin.py coverage by exercising the actual handlers
through their closure functions extracted from the router.

Covers:
- /invite unknown name (notion options available) → difflib suggestions
- /invite unknown name (no suggestions) → "not found" message
- /invite no name argument → usage hint
- /invite valid name → employee row created, 8-char code from alphabet, reply contains code
- /invite notion_client=None → creates code anyway (no schema check)
- /list empty → no-employees message
- /list with employees → formatted table
- /rename missing separator → usage hint
- /rename employee not found → error message
- /rename happy path → success message, snapshot reporter column updated
- /unbind no name → usage hint
- /unbind not found → error message
- /unbind happy path → success message, chat_id cleared
- /pause → sets paused state + warns no backfill
- /resume → clears paused state
"""

import hashlib
import json
import pytest
import pytest_asyncio

from notify_bot.config import Settings
from notify_bot.core.models import TaskState
from notify_bot.storage import db as db_mod, repo_employees, repo_invites, repo_snapshots, repo_state
from notify_bot.telegram import handlers_admin

_INVITE_ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def _make_settings(**overrides):
    base = dict(
        notion_token="x",
        telegram_token="123:ABC",
        notion_database_id="db1",
        admin_chat_ids=(999,),
        db_path=":memory:",
        invite_ttl=86400,
        invite_max_attempts=3,
        prop_assignee="Assign_new",
    )
    base.update(overrides)
    return Settings(**base)


@pytest_asyncio.fixture
async def conn():
    c = await db_mod.connect(":memory:")
    await db_mod.init_schema(c)
    yield c
    await c.close()


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies: list[dict] = []

    async def answer(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


def _get_handler(router, name: str):
    for obs_name in ("message", "callback_query"):
        obs = getattr(router, obs_name, None)
        if obs is None:
            continue
        for handler_obj in obs.handlers:
            fn = handler_obj.callback
            if fn.__name__ == name:
                return fn
    raise LookupError(f"Handler {name!r} not found in router")


class FakeNotionClient:
    def __init__(self, options: list[str]):
        self._options = options

    async def retrieve_db(self):
        return {
            "properties": {
                "Assign_new": {
                    "multi_select": {
                        "options": [{"name": n} for n in self._options]
                    }
                }
            }
        }


# ── /invite ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invite_no_name_shows_usage(conn):
    """/invite with no name → usage hint."""
    settings = _make_settings()
    r = handlers_admin.make_router(conn, settings)
    cmd_invite = _get_handler(r, "cmd_invite")

    msg = FakeMessage("/invite")
    await cmd_invite(msg)

    assert msg.replies
    assert "Использование" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_invite_unknown_name_with_suggestions(conn):
    """/invite with unknown name → difflib suggestions shown."""
    settings = _make_settings()
    notion_client = FakeNotionClient(["Иван Петров", "Иван Сидоров", "Ольга К"])
    r = handlers_admin.make_router(conn, settings, notion_client)
    cmd_invite = _get_handler(r, "cmd_invite")

    msg = FakeMessage("/invite Иван Петр")  # close to "Иван Петров"
    await cmd_invite(msg)

    assert msg.replies
    assert "Иван Петров" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_invite_unknown_name_no_suggestions(conn):
    """/invite with name far from any option → generic not-found message."""
    settings = _make_settings()
    notion_client = FakeNotionClient(["Alice", "Bob"])
    r = handlers_admin.make_router(conn, settings, notion_client)
    cmd_invite = _get_handler(r, "cmd_invite")

    msg = FakeMessage("/invite XXXXXXXXXXX")
    await cmd_invite(msg)

    assert msg.replies
    assert "не найдено" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_invite_valid_name_creates_8char_code(conn):
    """/invite valid name → code is 8 chars from allowed alphabet."""
    settings = _make_settings()
    notion_client = FakeNotionClient(["Мария Иванова"])
    r = handlers_admin.make_router(conn, settings, notion_client)
    cmd_invite = _get_handler(r, "cmd_invite")

    msg = FakeMessage("/invite Мария Иванова")
    await cmd_invite(msg)

    assert msg.replies
    reply_text = msg.replies[0]["text"]
    assert "Мария Иванова" in reply_text

    # Extract the code from the reply (it's inside <code>...</code>)
    import re
    match = re.search(r"<code>([A-Z0-9]{8})</code>", reply_text)
    assert match, f"No 8-char code found in: {reply_text}"
    code = match.group(1)
    assert len(code) == 8
    assert all(c in _INVITE_ALPHABET for c in code)


@pytest.mark.asyncio
async def test_invite_creates_employee_row(conn):
    """/invite creates employee row in DB (upsert_name)."""
    settings = _make_settings()
    notion_client = FakeNotionClient(["Новый Сотрудник"])
    r = handlers_admin.make_router(conn, settings, notion_client)
    cmd_invite = _get_handler(r, "cmd_invite")

    msg = FakeMessage("/invite Новый Сотрудник")
    await cmd_invite(msg)

    emp = await repo_employees.get_by_name(conn, "Новый Сотрудник")
    assert emp is not None


@pytest.mark.asyncio
async def test_invite_no_client_creates_code_anyway(conn):
    """/invite with notion_client=None → code created without schema check."""
    settings = _make_settings()
    r = handlers_admin.make_router(conn, settings, notion_client=None)
    cmd_invite = _get_handler(r, "cmd_invite")

    msg = FakeMessage("/invite Любое Имя")
    await cmd_invite(msg)

    assert msg.replies
    assert "Любое Имя" in msg.replies[0]["text"]


# ── /list ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_empty_employees(conn):
    """/list with no employees → empty message."""
    settings = _make_settings()
    r = handlers_admin.make_router(conn, settings)
    cmd_list = _get_handler(r, "cmd_list")

    msg = FakeMessage("/list")
    await cmd_list(msg)

    assert msg.replies
    assert "нет" in msg.replies[0]["text"].lower()


@pytest.mark.asyncio
async def test_list_shows_all_employees(conn):
    """/list shows all employee rows with chat_id and status."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Алиса")
    await repo_employees.bind(conn, "Алиса", 111)
    await repo_employees.upsert_name(conn, "Боб")
    await conn.commit()

    r = handlers_admin.make_router(conn, settings)
    cmd_list = _get_handler(r, "cmd_list")

    msg = FakeMessage("/list")
    await cmd_list(msg)

    assert msg.replies
    text = msg.replies[0]["text"]
    assert "Алиса" in text
    assert "Боб" in text
    assert "111" in text


# ── /rename ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_missing_separator_shows_usage(conn):
    """/rename without ' -> ' separator → usage hint."""
    settings = _make_settings()
    r = handlers_admin.make_router(conn, settings)
    cmd_rename = _get_handler(r, "cmd_rename")

    msg = FakeMessage("/rename Старое Имя Новое Имя")
    await cmd_rename(msg)

    assert msg.replies
    assert "Использование" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_rename_employee_not_found(conn):
    """/rename unknown employee → error message."""
    settings = _make_settings()
    r = handlers_admin.make_router(conn, settings)
    cmd_rename = _get_handler(r, "cmd_rename")

    msg = FakeMessage("/rename Несуществующий -> Новый")
    await cmd_rename(msg)

    assert msg.replies
    assert "не найден" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_rename_happy_path(conn):
    """/rename valid employee → success message, DB updated."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Старый")
    await repo_employees.bind(conn, "Старый", 555)
    await conn.commit()

    r = handlers_admin.make_router(conn, settings)
    cmd_rename = _get_handler(r, "cmd_rename")

    msg = FakeMessage("/rename Старый -> Новый")
    await cmd_rename(msg)

    assert msg.replies
    assert "Переименовано" in msg.replies[0]["text"]

    emp = await repo_employees.get_by_chat_id(conn, 555)
    assert emp["canonical_name"] == "Новый"


@pytest.mark.asyncio
async def test_rename_updates_snapshot_reporter(conn):
    """Rename updates reporter column in snapshots (not just assignees)."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Заказчик А")
    await conn.commit()

    snap = TaskState(
        page_id="r1",
        title="Task",
        status="В работе",
        assignees=frozenset(),
        reporter=frozenset(["Заказчик А"]),
        project_ids=(),
        due_start=None,
        due_end=None,
        url="https://notion.so/r1",
        last_edited_time="2024-01-01T10:00:00Z",
    )
    await repo_snapshots.upsert(conn, snap)
    await conn.commit()

    r = handlers_admin.make_router(conn, settings)
    cmd_rename = _get_handler(r, "cmd_rename")

    msg = FakeMessage("/rename Заказчик А -> Заказчик Б")
    await cmd_rename(msg)

    updated = await repo_snapshots.get(conn, "r1")
    assert "Заказчик Б" in updated.reporter
    assert "Заказчик А" not in updated.reporter


# ── /unbind ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unbind_no_name_shows_usage(conn):
    """/unbind with no name → usage hint."""
    settings = _make_settings()
    r = handlers_admin.make_router(conn, settings)
    cmd_unbind = _get_handler(r, "cmd_unbind")

    msg = FakeMessage("/unbind")
    await cmd_unbind(msg)

    assert "Использование" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_unbind_not_found(conn):
    """/unbind unknown employee → error message."""
    settings = _make_settings()
    r = handlers_admin.make_router(conn, settings)
    cmd_unbind = _get_handler(r, "cmd_unbind")

    msg = FakeMessage("/unbind Несуществующий")
    await cmd_unbind(msg)

    assert "не найден" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_unbind_happy_path(conn):
    """/unbind valid employee → chat_id cleared, success message."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Вера")
    await repo_employees.bind(conn, "Вера", 777)
    await conn.commit()

    r = handlers_admin.make_router(conn, settings)
    cmd_unbind = _get_handler(r, "cmd_unbind")

    msg = FakeMessage("/unbind Вера")
    await cmd_unbind(msg)

    assert msg.replies
    assert "снята" in msg.replies[0]["text"]

    emp = await repo_employees.get_by_name(conn, "Вера")
    assert emp["chat_id"] is None


# ── /pause / /resume ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_sets_paused_and_warns(conn):
    """/pause → paused state set, backfill warning in reply."""
    settings = _make_settings()
    r = handlers_admin.make_router(conn, settings)
    cmd_pause = _get_handler(r, "cmd_pause")

    msg = FakeMessage("/pause")
    await cmd_pause(msg)

    assert await repo_state.is_paused(conn)
    assert msg.replies
    # Warning about no backfill
    assert "НЕ будут" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_resume_clears_paused(conn):
    """/resume → paused=False, resume message."""
    settings = _make_settings()
    await repo_state.set_paused(conn, True)
    await conn.commit()

    r = handlers_admin.make_router(conn, settings)
    cmd_resume = _get_handler(r, "cmd_resume")

    msg = FakeMessage("/resume")
    await cmd_resume(msg)

    assert not await repo_state.is_paused(conn)
    assert msg.replies
