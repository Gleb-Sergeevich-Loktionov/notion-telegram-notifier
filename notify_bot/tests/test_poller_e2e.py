"""E2E poller tests using in-memory sqlite + fake Notion + fake sender.

AC-1..AC-9 from spec, plus cold-start no-send guarantee.
"""

import asyncio
import json
import pytest
import pytest_asyncio

from notify_bot.config import Settings
from notify_bot.core.models import TaskState
from notify_bot.notion.client import NotionRetryable
from notify_bot.notion import poller as poller_mod
from notify_bot.storage import db as db_mod, repo_employees, repo_snapshots, repo_state, repo_journal


# ── Fakes ──────────────────────────────────────────────


def _make_settings(**overrides):
    base = dict(
        notion_token="x",
        telegram_token="123:ABC",
        notion_database_id="db1",
        admin_chat_ids=(999,),
        db_path=":memory:",
        poll_interval=0,
        overlap_seconds=0,
        done_status="Готово",
    )
    base.update(overrides)
    return Settings(**base)


def _raw_page(
    page_id: str,
    title: str,
    status: str,
    assignees: list[str],
    let: str,
    reporter: list[str] | None = None,
) -> dict:
    """Build a minimal fake Notion page response."""
    return {
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "last_edited_time": let,
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": title}],
            },
            "Status": {
                "type": "status",
                "status": {"name": status},
            },
            "Assign_new": {
                "type": "multi_select",
                "multi_select": [{"name": n} for n in assignees],
            },
            "Заказчик_new": {
                "type": "select",
                "select": {"name": reporter[0]} if reporter else None,
            },
            "Проект": {"type": "relation", "relation": []},
            "Дата": {"type": "date", "date": None},
        },
    }


class FakeNotionClient:
    def __init__(self, pages: list[dict] | None = None):
        self.pages = pages or []
        self.calls: list = []

    async def query_incremental(self, after):
        self.calls.append(("query", after))
        return self.pages

    async def retrieve_db(self):
        return {}

    async def retrieve_page(self, page_id):
        return {}

    async def start_background_refresh(self):
        pass

    async def close(self):
        pass


class FakeSender:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[int, str]] = []
        self.fail = fail

    async def __call__(self, chat_id: int, text: str) -> bool:
        if self.fail:
            return False
        self.sent.append((chat_id, text))
        return True


@pytest_asyncio.fixture
async def conn():
    c = await db_mod.connect(":memory:")
    await db_mod.init_schema(c)
    yield c
    await c.close()


async def _run_one_cycle(conn, pages, settings=None, sender=None, checkpoint=None):
    """Run exactly one poller cycle and return the sender."""
    if settings is None:
        settings = _make_settings()
    if sender is None:
        sender = FakeSender()
    if checkpoint is not None:
        await repo_state.set_checkpoint(conn, checkpoint)
        await conn.commit()
    client = FakeNotionClient(pages)
    stop = asyncio.Event()
    stop.set()  # will stop after first iteration check but we call _run_cycle directly
    ckpt = await repo_state.get_checkpoint(conn)
    cold = ckpt is None
    await poller_mod._run_cycle(conn, client, settings, sender, ckpt, cold)
    return sender


# ── AC Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cold_start_no_sends(conn):
    """Cold start: snapshots stored, NO messages sent."""
    pages = [
        _raw_page("p1", "Task 1", "В работе", ["Alice"], "2024-01-01T10:00:00Z"),
        _raw_page("p2", "Task 2", "Сделать", ["Bob"], "2024-01-01T11:00:00Z"),
    ]
    sender = await _run_one_cycle(conn, pages)

    assert sender.sent == []  # no sends during cold start

    # Snapshots written
    snap1 = await repo_snapshots.get(conn, "p1")
    assert snap1 is not None
    assert snap1.title == "Task 1"

    # Checkpoint set to max last_edited_time
    ckpt = await repo_state.get_checkpoint(conn)
    assert ckpt == "2024-01-01T11:00:00Z"


@pytest.mark.asyncio
async def test_ac1_new_assignee_notification(conn):
    """AC-1: New page with assignee → bound employee gets notification."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.bind(conn, "Alice", 111)
    await conn.commit()

    # Cold start first
    await _run_one_cycle(conn, [
        _raw_page("p1", "Task A", "В работе", ["Alice"], "2024-01-01T10:00:00Z"),
    ])

    # New page appears (incremental, after cold start checkpoint is set)
    sender = FakeSender()
    ckpt = await repo_state.get_checkpoint(conn)
    client = FakeNotionClient([
        _raw_page("p2", "New Task", "Сделать", ["Alice"], "2024-01-02T10:00:00Z"),
    ])
    await poller_mod._run_cycle(conn, client, settings, sender, ckpt, cold=False)

    assert len(sender.sent) == 1
    chat_id, text = sender.sent[0]
    assert chat_id == 111
    assert "New Task" in text


@pytest.mark.asyncio
async def test_ac2_status_change_notifies_assignees_and_reporter(conn):
    """AC-2: Status change notifies all assignees + reporter."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.upsert_name(conn, "Reporter")
    await repo_employees.bind(conn, "Alice", 111)
    await repo_employees.bind(conn, "Reporter", 222)
    await conn.commit()

    # Seed snapshot with old status
    snap = TaskState(
        page_id="p1", title="T", status="Сделать",
        assignees=frozenset(["Alice"]), reporter=frozenset(["Reporter"]),
        project_ids=(), due_start=None, due_end=None,
        url="https://notion.so/p1", last_edited_time="2024-01-01T10:00:00Z",
    )
    await repo_snapshots.upsert(conn, snap)
    await repo_state.set_checkpoint(conn, "2024-01-01T10:00:00Z")
    await conn.commit()

    sender = FakeSender()
    client = FakeNotionClient([
        _raw_page("p1", "T", "В работе", ["Alice"], "2024-01-02T10:00:00Z",
                  reporter=["Reporter"]),
    ])
    await poller_mod._run_cycle(conn, client, settings, sender, "2024-01-01T10:00:00Z", cold=False)

    chat_ids = {c for c, _ in sender.sent}
    assert 111 in chat_ids  # assignee
    assert 222 in chat_ids  # reporter


@pytest.mark.asyncio
async def test_ac3_unbound_employee_no_send(conn):
    """AC-3: Unbound employee → no notification sent (logged)."""
    settings = _make_settings()
    # Employee exists but not bound (no chat_id)
    await repo_employees.upsert_name(conn, "Unbound")
    await conn.commit()

    await repo_state.set_checkpoint(conn, "2024-01-01T09:00:00Z")
    await conn.commit()

    sender = FakeSender()
    client = FakeNotionClient([
        _raw_page("p1", "Task", "Сделать", ["Unbound"], "2024-01-02T10:00:00Z"),
    ])
    await poller_mod._run_cycle(conn, client, settings, sender, "2024-01-01T09:00:00Z", cold=False)

    assert sender.sent == []


@pytest.mark.asyncio
async def test_ac4_done_status_no_new_assignee_event(conn):
    """AC-4: New assignee added when status=Готово → no notification (BR-4)."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.bind(conn, "Alice", 111)
    await conn.commit()

    # Seed snapshot: no assignees, status already Готово
    snap = TaskState(
        page_id="p1", title="Done Task", status="Готово",
        assignees=frozenset(), reporter=frozenset(),
        project_ids=(), due_start=None, due_end=None,
        url="https://notion.so/p1", last_edited_time="2024-01-01T10:00:00Z",
    )
    await repo_snapshots.upsert(conn, snap)
    await repo_state.set_checkpoint(conn, "2024-01-01T10:00:00Z")
    await conn.commit()

    sender = FakeSender()
    client = FakeNotionClient([
        _raw_page("p1", "Done Task", "Готово", ["Alice"], "2024-01-02T10:00:00Z"),
    ])
    await poller_mod._run_cycle(conn, client, settings, sender, "2024-01-01T10:00:00Z", cold=False)

    # Alice added but status=Готово → BR-4 suppresses NEW_ASSIGNEE
    new_assignee_sends = [t for _, t in sender.sent if "Новая задача" in t]
    assert new_assignee_sends == []


@pytest.mark.asyncio
async def test_ac5_paused_suppresses_notifications(conn):
    """AC-5: Paused state → notifications suppressed, not sent."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.bind(conn, "Alice", 111)
    await repo_state.set_paused(conn, True)
    await repo_state.set_checkpoint(conn, "2024-01-01T09:00:00Z")
    await conn.commit()

    sender = FakeSender()
    client = FakeNotionClient([
        _raw_page("p2", "Task X", "Сделать", ["Alice"], "2024-01-02T10:00:00Z"),
    ])
    await poller_mod._run_cycle(conn, client, settings, sender, "2024-01-01T09:00:00Z", cold=False)

    assert sender.sent == []


@pytest.mark.asyncio
async def test_ac6_dedup_prevents_double_send(conn):
    """AC-6: Same dedup_key → message sent exactly once."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.bind(conn, "Alice", 111)
    await repo_state.set_checkpoint(conn, "2024-01-01T09:00:00Z")
    await conn.commit()

    page = _raw_page("p1", "Task", "Сделать", ["Alice"], "2024-01-02T10:00:00Z")
    client = FakeNotionClient([page])

    sender1 = FakeSender()
    await poller_mod._run_cycle(conn, client, settings, sender1, "2024-01-01T09:00:00Z", cold=False)

    sender2 = FakeSender()
    await poller_mod._run_cycle(conn, client, settings, sender2, "2024-01-01T09:00:00Z", cold=False)

    # First cycle sends, second cycle deduped
    assert len(sender1.sent) == 1
    assert len(sender2.sent) == 0


@pytest.mark.asyncio
async def test_ac7_checkpoint_advances_after_cycle(conn):
    """AC-7: Checkpoint advances to max last_edited_time after successful cycle."""
    pages = [
        _raw_page("p1", "T1", "В работе", [], "2024-01-01T10:00:00Z"),
        _raw_page("p2", "T2", "Сделать", [], "2024-01-03T15:00:00Z"),
    ]
    await _run_one_cycle(conn, pages)

    ckpt = await repo_state.get_checkpoint(conn)
    assert ckpt == "2024-01-03T15:00:00Z"


@pytest.mark.asyncio
async def test_ac8_readded_assignee_sends_again(conn):
    """AC-8: Name removed then re-added with new last_edited_time → new notification."""
    settings = _make_settings()
    await repo_employees.upsert_name(conn, "Alice")
    await repo_employees.bind(conn, "Alice", 111)
    await conn.commit()

    # Initial state: Alice assigned
    snap = TaskState(
        page_id="p1", title="T", status="В работе",
        assignees=frozenset(["Alice"]), reporter=frozenset(),
        project_ids=(), due_start=None, due_end=None,
        url="https://notion.so/p1", last_edited_time="2024-01-01T10:00:00Z",
    )
    await repo_snapshots.upsert(conn, snap)
    await repo_state.set_checkpoint(conn, "2024-01-01T10:00:00Z")
    await conn.commit()

    # Alice removed
    snap2 = TaskState(
        page_id="p1", title="T", status="В работе",
        assignees=frozenset(), reporter=frozenset(),
        project_ids=(), due_start=None, due_end=None,
        url="https://notion.so/p1", last_edited_time="2024-01-02T10:00:00Z",
    )
    await repo_snapshots.upsert(conn, snap2)
    await repo_state.set_checkpoint(conn, "2024-01-02T10:00:00Z")
    await conn.commit()

    # Alice re-added with new last_edited_time
    sender = FakeSender()
    client = FakeNotionClient([
        _raw_page("p1", "T", "В работе", ["Alice"], "2024-01-03T10:00:00Z"),
    ])
    await poller_mod._run_cycle(conn, client, settings, sender, "2024-01-02T10:00:00Z", cold=False)

    assert len(sender.sent) == 1
    assert sender.sent[0][0] == 111


@pytest.mark.asyncio
async def test_ac9_notion_retryable_does_not_move_checkpoint(conn):
    """AC-9: NotionRetryable error → checkpoint stays, retry next cycle."""
    settings = _make_settings()
    await repo_state.set_checkpoint(conn, "2024-01-01T10:00:00Z")
    await conn.commit()

    class ErrorClient:
        async def query_incremental(self, after):
            raise NotionRetryable("timeout")
        async def retrieve_db(self):
            return {}
        async def retrieve_page(self, pid):
            return {}
        async def start_background_refresh(self):
            pass

    sender = FakeSender()
    try:
        await poller_mod._run_cycle(
            conn, ErrorClient(), settings, sender, "2024-01-01T10:00:00Z", cold=False
        )
    except NotionRetryable:
        pass  # expected to propagate

    ckpt = await repo_state.get_checkpoint(conn)
    assert ckpt == "2024-01-01T10:00:00Z"  # checkpoint NOT moved
