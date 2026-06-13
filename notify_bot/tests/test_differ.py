"""Tests for core/differ.py — full functional matrix from spec §17."""

import pytest

from notify_bot.core.differ import diff
from notify_bot.core.models import EventKind, TaskState


def make_task(
    page_id="p1",
    title="Test Task",
    status="В работе",
    assignees=("Alice",),
    reporter=(),
    project_ids=(),
    due_start=None,
    due_end=None,
    url="https://notion.so/p1",
    last_edited_time="2024-01-01T10:00:00Z",
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


DONE = "Готово"


# --- cold start ---

def test_cold_start_returns_empty():
    task = make_task()
    assert diff(None, task, cold_start=True) == []


def test_cold_start_with_existing_old_returns_empty():
    old = make_task(status="Сделать")
    new = make_task(status=DONE)
    assert diff(old, new, cold_start=True) == []


# --- new page (old=None, not cold start) ---

def test_new_page_with_assignee_not_done_emits_new_assignee():
    task = make_task(assignees=("Alice",), status="Сделать")
    events = diff(None, task, cold_start=False)
    assert len(events) == 1
    assert events[0].kind == EventKind.NEW_ASSIGNEE
    assert events[0].target_name == "Alice"


def test_new_page_multiple_assignees_emits_one_per_assignee():
    task = make_task(assignees=("Alice", "Bob"), status="В работе")
    events = diff(None, task, cold_start=False)
    names = {e.target_name for e in events}
    assert names == {"Alice", "Bob"}
    assert all(e.kind == EventKind.NEW_ASSIGNEE for e in events)


def test_new_page_done_status_no_events():
    task = make_task(assignees=("Alice",), status=DONE)
    assert diff(None, task, cold_start=False) == []


def test_new_page_empty_assignees_no_events():
    task = make_task(assignees=(), status="В работе")
    assert diff(None, task, cold_start=False) == []


def test_new_page_no_status_change_event():
    """No STATUS_CHANGED for brand new page — there's no prior state to transition from."""
    task = make_task(assignees=("Alice",), status="В работе")
    events = diff(None, task, cold_start=False)
    assert all(e.kind == EventKind.NEW_ASSIGNEE for e in events)


# --- existing page ---

def test_added_assignee_emits_new_assignee():
    old = make_task(assignees=("Alice",), status="В работе")
    new = make_task(assignees=("Alice", "Bob"), status="В работе")
    events = diff(old, new, cold_start=False)
    assert len(events) == 1
    assert events[0].kind == EventKind.NEW_ASSIGNEE
    assert events[0].target_name == "Bob"


def test_removed_assignee_no_event():
    """HR-1: removing a name is not an event."""
    old = make_task(assignees=("Alice", "Bob"), status="В работе")
    new = make_task(assignees=("Alice",), status="В работе")
    events = diff(old, new, cold_start=False)
    assert events == []


def test_status_change_emits_status_changed():
    old = make_task(status="Сделать")
    new = make_task(status="В работе")
    events = diff(old, new, cold_start=False)
    assert len(events) == 1
    e = events[0]
    assert e.kind == EventKind.STATUS_CHANGED
    assert e.old_status == "Сделать"
    assert e.new_status == "В работе"


def test_simultaneous_add_and_status_change():
    old = make_task(assignees=("Alice",), status="Сделать")
    new = make_task(assignees=("Alice", "Bob"), status="В работе")
    events = diff(old, new, cold_start=False)
    kinds = {e.kind for e in events}
    assert EventKind.NEW_ASSIGNEE in kinds
    assert EventKind.STATUS_CHANGED in kinds


def test_added_assignee_done_no_new_assignee_event():
    """BR-4: new assignee when status=Готово -> suppressed."""
    old = make_task(assignees=("Alice",), status="На проверке")
    new = make_task(assignees=("Alice", "Bob"), status=DONE)
    events = diff(old, new, cold_start=False)
    assert all(e.kind == EventKind.STATUS_CHANGED for e in events)


def test_status_none_to_none_no_status_changed():
    old = make_task(status=None)
    new = make_task(status=None)
    assert diff(old, new, cold_start=False) == []


def test_status_none_new_value_emits_status_changed():
    old = make_task(status=None)
    new = make_task(status="В работе")
    events = diff(old, new, cold_start=False)
    assert any(e.kind == EventKind.STATUS_CHANGED for e in events)


def test_status_new_is_none_no_status_changed():
    """new.status is None -> no STATUS_CHANGED (spec §4 guard)."""
    old = make_task(status="В работе")
    new = make_task(status=None)
    events = diff(old, new, cold_start=False)
    assert all(e.kind != EventKind.STATUS_CHANGED for e in events)


def test_no_changes_no_events():
    task = make_task()
    assert diff(task, task, cold_start=False) == []


# --- custom done_status ---

def test_custom_done_status_parameter():
    task = make_task(assignees=("Alice",), status="Done")
    events = diff(None, task, cold_start=False, done_status="Done")
    assert events == []


# --- AC-8: re-added name with new last_edited_time is NOT suppressed by differ ---
# (dedup lives in journal; differ always emits the event for re-added names)

def test_ac8_readded_name_emits_event():
    old = make_task(assignees=(), status="В работе", last_edited_time="2024-01-02T00:00:00Z")
    new = make_task(assignees=("Alice",), status="В работе", last_edited_time="2024-01-03T00:00:00Z")
    events = diff(old, new, cold_start=False)
    assert any(e.target_name == "Alice" for e in events)
