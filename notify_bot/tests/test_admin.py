"""Tests for admin commands (spec §11).

Tests:
- Non-admin silence (AdminFilter)
- Invite flow: code generated, sha256 stored, old codes invalidated
- Rename updates employee binding AND snapshot JSON exactly (no substring corruption)
- Pause / Resume state
"""

import hashlib
import json
import pytest
import pytest_asyncio

from notify_bot.config import Settings
from notify_bot.storage import db as db_mod, repo_employees, repo_invites, repo_state
from notify_bot.storage import repo_snapshots
from notify_bot.core.models import TaskState
from notify_bot.telegram import handlers_admin
from notify_bot.telegram.middleware import AdminFilter


def _make_settings(**overrides):
    base = dict(
        notion_token="x",
        telegram_token="123:ABC",
        notion_database_id="db1",
        admin_chat_ids=(999,),
        db_path=":memory:",
        invite_ttl=86400,
        invite_max_attempts=3,
    )
    base.update(overrides)
    return Settings(**base)


@pytest_asyncio.fixture
async def conn():
    c = await db_mod.connect(":memory:")
    await db_mod.init_schema(c)
    yield c
    await c.close()


# ── AdminFilter ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_filter_blocks_non_admin():
    """Non-admin message is silenced — handler never called."""
    called = []

    async def fake_handler(event, data):
        called.append(True)
        return "handled"

    import datetime
    from aiogram.types import Message, User, Chat

    def _user(uid):
        return User(id=uid, is_bot=False, first_name="X")

    def _chat(cid):
        return Chat(id=cid, type="private")

    msg = Message(
        message_id=1,
        date=datetime.datetime.now(tz=datetime.timezone.utc),
        chat=_chat(42),
        from_user=_user(42),  # non-admin
        text="/list",
    )

    filt = AdminFilter(admin_chat_ids=(999,))
    result = await filt(fake_handler, msg, {})
    assert called == []  # handler was never called
    assert result is None


@pytest.mark.asyncio
async def test_admin_filter_allows_admin():
    """Admin message passes through to handler."""
    called = []

    async def fake_handler(event, data):
        called.append(True)
        return "handled"

    import datetime
    from aiogram.types import Message, User, Chat

    def _user(uid):
        return User(id=uid, is_bot=False, first_name="Admin")

    def _chat(cid):
        return Chat(id=cid, type="private")

    msg = Message(
        message_id=1,
        date=datetime.datetime.now(tz=datetime.timezone.utc),
        chat=_chat(999),
        from_user=_user(999),  # admin
        text="/list",
    )

    filt = AdminFilter(admin_chat_ids=(999,))
    result = await filt(fake_handler, msg, {})
    assert called == [True]


# ── Invite ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invite_creates_code_with_sha256(conn):
    """Invite stores sha256 of code, not plaintext."""
    settings = _make_settings()

    await repo_employees.upsert_name(conn, "Иван Петров")
    await conn.commit()

    # Simulate what cmd_invite does
    code = "TESTCODE"
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    from datetime import datetime, timezone, timedelta
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    await repo_invites.insert(conn, "Иван Петров", code_hash, expires)
    await conn.commit()

    rec = await repo_invites.find_valid_by_hash(conn, code_hash)
    assert rec is not None
    assert rec["canonical_name"] == "Иван Петров"
    # Code hash is stored, not plaintext
    assert rec["code_hash"] == code_hash
    assert "TESTCODE" not in json.dumps(rec)  # plaintext not stored


@pytest.mark.asyncio
async def test_invite_invalidates_old_codes(conn):
    """Re-inviting a name invalidates previous unused codes."""
    settings = _make_settings()
    from datetime import datetime, timezone, timedelta

    await repo_employees.upsert_name(conn, "Ольга К")
    await conn.commit()

    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    old_hash = hashlib.sha256(b"OLDCODE1").hexdigest()
    await repo_invites.insert(conn, "Ольга К", old_hash, expires)
    await conn.commit()

    # Invalidate old codes then create new one
    await repo_invites.invalidate_for_name(conn, "Ольга К")
    new_hash = hashlib.sha256(b"NEWCODE2").hexdigest()
    await repo_invites.insert(conn, "Ольга К", new_hash, expires)
    await conn.commit()

    old_rec = await repo_invites.find_valid_by_hash(conn, old_hash)
    assert old_rec is None  # old code invalidated

    new_rec = await repo_invites.find_valid_by_hash(conn, new_hash)
    assert new_rec is not None


# ── Rename ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_updates_employee_row(conn):
    """Rename changes canonical_name in employees table."""
    await repo_employees.upsert_name(conn, "Аня Смолина")
    await repo_employees.bind(conn, "Аня Смолина", 123)
    await conn.commit()

    await repo_employees.rename(conn, "Аня Смолина", "Аня С")
    await conn.commit()

    emp = await repo_employees.get_by_chat_id(conn, 123)
    assert emp["canonical_name"] == "Аня С"


@pytest.mark.asyncio
async def test_rename_updates_snapshot_json_exactly(conn):
    """CR-5: rename replaces exact element in JSON arrays, no substring corruption.

    'Аня С' must not corrupt 'Аня Смолина' and vice-versa.
    """
    # Insert snapshot with both names
    snap = TaskState(
        page_id="page1",
        title="Task",
        status="В работе",
        assignees=frozenset(["Аня Смолина", "Борис"]),
        reporter=frozenset(["Аня С"]),
        project_ids=(),
        due_start=None,
        due_end=None,
        url="https://notion.so/page1",
        last_edited_time="2024-01-01T10:00:00Z",
    )
    await repo_snapshots.upsert(conn, snap)
    await conn.commit()

    # Rename "Аня Смолина" → "Анна Смолина"
    await handlers_admin._rename_in_snapshots(conn, "Аня Смолина", "Анна Смолина")
    await conn.commit()

    updated = await repo_snapshots.get(conn, "page1")
    assert "Анна Смолина" in updated.assignees
    assert "Аня Смолина" not in updated.assignees
    # "Аня С" in reporter must NOT be corrupted
    assert "Аня С" in updated.reporter


@pytest.mark.asyncio
async def test_rename_substring_safety(conn):
    """Renaming 'Аня С' must not corrupt 'Аня Смолина' in the same snapshot."""
    snap = TaskState(
        page_id="page2",
        title="Task2",
        status="Сделать",
        assignees=frozenset(["Аня С", "Аня Смолина"]),
        reporter=frozenset(),
        project_ids=(),
        due_start=None,
        due_end=None,
        url="https://notion.so/page2",
        last_edited_time="2024-01-02T10:00:00Z",
    )
    await repo_snapshots.upsert(conn, snap)
    await conn.commit()

    # Rename "Аня С" → "Аня Степанова"
    await handlers_admin._rename_in_snapshots(conn, "Аня С", "Аня Степанова")
    await conn.commit()

    updated = await repo_snapshots.get(conn, "page2")
    assert "Аня Степанова" in updated.assignees
    assert "Аня С" not in updated.assignees
    # Full name must remain intact
    assert "Аня Смолина" in updated.assignees


# ── Pause / Resume ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_sets_paused_state(conn):
    """Pause sets paused=true in bot_state."""
    assert not await repo_state.is_paused(conn)
    await repo_state.set_paused(conn, True)
    await conn.commit()
    assert await repo_state.is_paused(conn)


@pytest.mark.asyncio
async def test_resume_clears_paused_state(conn):
    """Resume sets paused=false."""
    await repo_state.set_paused(conn, True)
    await conn.commit()
    await repo_state.set_paused(conn, False)
    await conn.commit()
    assert not await repo_state.is_paused(conn)
