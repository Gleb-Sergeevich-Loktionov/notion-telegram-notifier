"""Integration tests for all storage repositories on :memory: SQLite."""

import pytest
import pytest_asyncio
import aiosqlite

from notify_bot.storage.db import connect, init_schema
from notify_bot.storage import (
    repo_employees,
    repo_invites,
    repo_snapshots,
    repo_journal,
    repo_state,
    repo_projects,
)
from notify_bot.core.models import TaskState


@pytest_asyncio.fixture
async def conn():
    """In-memory aiosqlite connection with schema applied."""
    db = await connect(":memory:")
    await init_schema(db)
    yield db
    await db.close()


def make_task(
    page_id="p1",
    title="Task",
    status="В работе",
    assignees=("Alice",),
    reporter=("Bob",),
    project_ids=("proj1",),
    due_start="2024-03-01",
    due_end=None,
    url="https://notion.so/p1",
    last_edited_time="2024-01-01T00:00:00Z",
):
    return TaskState(
        page_id=page_id,
        title=title,
        status=status,
        assignees=frozenset(assignees),
        reporter=frozenset(reporter),
        project_ids=tuple(project_ids),
        due_start=due_start,
        due_end=due_end,
        url=url,
        last_edited_time=last_edited_time,
    )


# --- repo_employees ---

@pytest.mark.asyncio
async def test_employee_upsert_and_get(conn):
    await repo_employees.upsert_name(conn, "Alice")
    await conn.commit()
    row = await repo_employees.get_by_name(conn, "Alice")
    assert row is not None
    assert row["canonical_name"] == "Alice"
    assert row["chat_id"] is None


@pytest.mark.asyncio
async def test_employee_bind_and_is_bound(conn):
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.bind(conn, "Alice", 1001)
    await conn.commit()
    assert await repo_employees.is_bound(conn, 1001)


@pytest.mark.asyncio
async def test_employee_unbind(conn):
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.bind(conn, "Alice", 1001)
    await conn.commit()
    await repo_employees.unbind(conn, "Alice")
    await conn.commit()
    assert not await repo_employees.is_bound(conn, 1001)


@pytest.mark.asyncio
async def test_employee_rename(conn):
    await repo_employees.upsert_name(conn, "Alice")
    await conn.commit()
    await repo_employees.rename(conn, "Alice", "Alicia")
    await conn.commit()
    assert await repo_employees.get_by_name(conn, "Alicia") is not None
    assert await repo_employees.get_by_name(conn, "Alice") is None


@pytest.mark.asyncio
async def test_employee_bindings_map(conn):
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.upsert_name(conn, "Bob")
    await repo_employees.bind(conn, "Alice", 101)
    await conn.commit()
    bindings = await repo_employees.get_bindings_map(conn)
    assert bindings == {"Alice": 101}


# --- repo_invites ---

@pytest.mark.asyncio
async def test_invite_insert_and_find(conn):
    await repo_employees.upsert_name(conn, "Alice")
    await conn.commit()
    await repo_invites.insert(conn, "Alice", "hash123", "2099-01-01T00:00:00Z")
    await conn.commit()
    row = await repo_invites.find_valid_by_hash(conn, "hash123")
    assert row is not None
    assert row["canonical_name"] == "Alice"


@pytest.mark.asyncio
async def test_invite_mark_used(conn):
    await repo_employees.upsert_name(conn, "Alice")
    await conn.commit()
    invite_id = await repo_invites.insert(conn, "Alice", "hash456", "2099-01-01T00:00:00Z")
    await conn.commit()
    await repo_invites.mark_used(conn, invite_id)
    await conn.commit()
    row = await repo_invites.find_valid_by_hash(conn, "hash456")
    assert row is None


@pytest.mark.asyncio
async def test_invite_expired_not_found(conn):
    await repo_employees.upsert_name(conn, "Alice")
    await conn.commit()
    await repo_invites.insert(conn, "Alice", "hash789", "2000-01-01T00:00:00Z")
    await conn.commit()
    row = await repo_invites.find_valid_by_hash(conn, "hash789")
    assert row is None


# --- repo_snapshots ---

@pytest.mark.asyncio
async def test_snapshot_upsert_and_get(conn):
    task = make_task()
    await repo_snapshots.upsert(conn, task)
    await conn.commit()
    loaded = await repo_snapshots.get(conn, "p1")
    assert loaded is not None
    assert loaded.page_id == "p1"
    assert loaded.title == "Task"
    assert "Alice" in loaded.assignees
    assert "Bob" in loaded.reporter
    assert "proj1" in loaded.project_ids


@pytest.mark.asyncio
async def test_snapshot_get_missing_returns_none(conn):
    result = await repo_snapshots.get(conn, "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_snapshot_upsert_updates(conn):
    task1 = make_task(title="Old", last_edited_time="2024-01-01T00:00:00Z")
    task2 = make_task(title="New", last_edited_time="2024-01-02T00:00:00Z")
    await repo_snapshots.upsert(conn, task1)
    await conn.commit()
    await repo_snapshots.upsert(conn, task2)
    await conn.commit()
    loaded = await repo_snapshots.get(conn, "p1")
    assert loaded.title == "New"


@pytest.mark.asyncio
async def test_snapshot_roundtrip_frozen_types(conn):
    task = make_task(assignees=("Alice", "Bob"), reporter=("Charlie",), project_ids=("x", "y"))
    await repo_snapshots.upsert(conn, task)
    await conn.commit()
    loaded = await repo_snapshots.get(conn, "p1")
    assert isinstance(loaded.assignees, frozenset)
    assert isinstance(loaded.project_ids, tuple)


# --- repo_journal ---

@pytest.mark.asyncio
async def test_journal_insert_and_exists(conn):
    await repo_journal.insert(conn, "key1", "p1", "new_assignee", 101)
    await conn.commit()
    assert await repo_journal.exists(conn, "key1")


@pytest.mark.asyncio
async def test_journal_not_exists(conn):
    assert not await repo_journal.exists(conn, "no_such_key")


@pytest.mark.asyncio
async def test_journal_insert_or_ignore_duplicate(conn):
    await repo_journal.insert(conn, "key1", "p1", "new_assignee", 101)
    await conn.commit()
    # Should not raise
    await repo_journal.insert(conn, "key1", "p1", "new_assignee", 101)
    await conn.commit()
    assert await repo_journal.exists(conn, "key1")


# --- repo_state ---

@pytest.mark.asyncio
async def test_state_checkpoint_none_initially(conn):
    assert await repo_state.get_checkpoint(conn) is None


@pytest.mark.asyncio
async def test_state_set_and_get_checkpoint(conn):
    await repo_state.set_checkpoint(conn, "2024-06-01T00:00:00Z")
    await conn.commit()
    val = await repo_state.get_checkpoint(conn)
    assert val == "2024-06-01T00:00:00Z"


@pytest.mark.asyncio
async def test_state_checkpoint_idempotent_update(conn):
    await repo_state.set_checkpoint(conn, "2024-06-01T00:00:00Z")
    await conn.commit()
    await repo_state.set_checkpoint(conn, "2024-07-01T00:00:00Z")
    await conn.commit()
    assert await repo_state.get_checkpoint(conn) == "2024-07-01T00:00:00Z"


@pytest.mark.asyncio
async def test_state_paused_false_initially(conn):
    assert not await repo_state.is_paused(conn)


@pytest.mark.asyncio
async def test_state_set_paused_true(conn):
    await repo_state.set_paused(conn, True)
    await conn.commit()
    assert await repo_state.is_paused(conn)


@pytest.mark.asyncio
async def test_state_set_paused_false(conn):
    await repo_state.set_paused(conn, True)
    await conn.commit()
    await repo_state.set_paused(conn, False)
    await conn.commit()
    assert not await repo_state.is_paused(conn)


# --- repo_projects ---

@pytest.mark.asyncio
async def test_project_upsert_and_get(conn):
    await repo_projects.upsert(conn, "proj-1", "My Project")
    await conn.commit()
    row = await repo_projects.get(conn, "proj-1")
    assert row["title"] == "My Project"


@pytest.mark.asyncio
async def test_project_get_title(conn):
    await repo_projects.upsert(conn, "proj-1", "My Project")
    await conn.commit()
    assert await repo_projects.get_title(conn, "proj-1") == "My Project"


@pytest.mark.asyncio
async def test_project_get_missing_returns_none(conn):
    assert await repo_projects.get_title(conn, "nope") is None


@pytest.mark.asyncio
async def test_project_upsert_updates(conn):
    await repo_projects.upsert(conn, "proj-1", "Old Name")
    await conn.commit()
    await repo_projects.upsert(conn, "proj-1", "New Name")
    await conn.commit()
    assert await repo_projects.get_title(conn, "proj-1") == "New Name"


# --- AC-8/AC-9 dedup semantics at storage level ---

@pytest.mark.asyncio
async def test_ac8_readded_name_new_let_not_deduped(conn):
    """AC-8: same page+kind+name but different last_edited_time -> different key -> not deduped."""
    from notify_bot.core.dedup import build_dedup_key
    from notify_bot.core.models import EventKind

    key1 = build_dedup_key("p1", EventKind.NEW_ASSIGNEE, "Alice", "2024-01-01T00:00:00Z", 101)
    key2 = build_dedup_key("p1", EventKind.NEW_ASSIGNEE, "Alice", "2024-02-01T00:00:00Z", 101)

    await repo_journal.insert(conn, key1, "p1", "new_assignee", 101)
    await conn.commit()

    assert await repo_journal.exists(conn, key1)
    assert not await repo_journal.exists(conn, key2)


@pytest.mark.asyncio
async def test_ac9_status_changed_same_let_deduped(conn):
    """AC-9 dedup: same observation (same let) -> key exists -> skip."""
    from notify_bot.core.dedup import build_dedup_key
    from notify_bot.core.models import EventKind

    key = build_dedup_key("p1", EventKind.STATUS_CHANGED, "Готово", "2024-01-01T00:00:00Z", 101)
    await repo_journal.insert(conn, key, "p1", "status_changed", 101)
    await conn.commit()
    assert await repo_journal.exists(conn, key)
