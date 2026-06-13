"""Tests for core/router.py — BR-5, BR-6, routing matrix."""

from notify_bot.core.models import Event, EventKind, TaskState
from notify_bot.core.router import route


def make_task(
    page_id="p1",
    assignees=("Alice",),
    reporter=(),
    status="В работе",
    last_edited_time="2024-01-01T10:00:00Z",
):
    return TaskState(
        page_id=page_id,
        title="Task",
        status=status,
        assignees=frozenset(assignees),
        reporter=frozenset(reporter),
        project_ids=(),
        due_start=None,
        due_end=None,
        url="https://notion.so/p1",
        last_edited_time=last_edited_time,
    )


def _renderer(event, task, project_name, tz):
    return f"text:{event.kind.value}"


BINDINGS = {"Alice": 101, "Bob": 102, "Charlie": 103}


def test_new_assignee_only_added_person_receives():
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Bob")
    task = make_task(assignees=("Alice", "Bob"))
    plan = route([event], task, BINDINGS, _renderer)
    chat_ids = {item.chat_id for item in plan}
    assert chat_ids == {102}


def test_status_changed_all_assignees_and_reporter_receive():
    event = Event("p1", EventKind.STATUS_CHANGED, old_status="Сделать", new_status="Готово")
    task = make_task(assignees=("Alice", "Bob"), reporter=("Charlie",))
    plan = route([event], task, BINDINGS, _renderer)
    chat_ids = {item.chat_id for item in plan}
    assert chat_ids == {101, 102, 103}


def test_br5_same_person_both_roles_one_push():
    """BR-5: assignee == reporter -> one NotificationPlanItem."""
    event = Event("p1", EventKind.STATUS_CHANGED, old_status="A", new_status="B")
    task = make_task(assignees=("Alice",), reporter=("Alice",))
    plan = route([event], task, {"Alice": 101}, _renderer)
    assert len(plan) == 1
    assert plan[0].chat_id == 101


def test_br6_unbound_recipient_not_in_plan(caplog):
    """BR-6: unbound name -> log, not in plan."""
    import logging
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Unknown")
    task = make_task(assignees=("Unknown",))
    with caplog.at_level(logging.INFO, logger="notify_bot.core.router"):
        plan = route([event], task, {}, _renderer)
    assert plan == []
    assert "unbound_recipient" in caplog.text


def test_empty_events_returns_empty_plan():
    task = make_task()
    assert route([], task, BINDINGS, _renderer) == []


def test_plan_item_has_dedup_key():
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    task = make_task(assignees=("Alice",), last_edited_time="2024-01-01T00:00:00Z")
    plan = route([event], task, {"Alice": 101}, _renderer)
    assert len(plan) == 1
    assert "p1:new_assignee:Alice:2024-01-01T00:00:00Z:101" == plan[0].dedup_key


def test_plan_item_has_text():
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    task = make_task(assignees=("Alice",))
    plan = route([event], task, {"Alice": 101}, _renderer)
    assert plan[0].text == "text:new_assignee"


def test_status_changed_dedup_key_uses_new_status():
    event = Event("p1", EventKind.STATUS_CHANGED, old_status="A", new_status="Готово")
    task = make_task(assignees=("Alice",), last_edited_time="2024-05-01T00:00:00Z")
    plan = route([event], task, {"Alice": 101}, _renderer)
    assert "status_changed:Готово" in plan[0].dedup_key
