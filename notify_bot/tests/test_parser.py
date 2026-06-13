"""Tests for notion/parser.py — property types, fallbacks, warn-once."""

import logging

import pytest

from notify_bot.notion.parser import _warned_missing, parse
from notify_bot.core.models import TaskState

DEFAULT_CONFIG = {
    "title": "Name",
    "assignee": "Assign_new",
    "reporter": "Заказчик_new",
    "status": "Status",
    "project": "Проект",
    "due": "Дата",
}


def make_raw(
    page_id="page-1",
    url="https://notion.so/page-1",
    last_edited_time="2024-01-01T00:00:00Z",
    props=None,
):
    return {
        "id": page_id,
        "url": url,
        "last_edited_time": last_edited_time,
        "properties": props or {},
    }


def make_props(
    title="Task Name",
    assignees=("Alice",),
    reporter_type="multi_select",
    reporter=("Bob",),
    status_type="status",
    status="В работе",
    project_ids=(),
    due_start=None,
    due_end=None,
):
    """Build a Notion properties dict with configurable field types."""
    props = {
        "Name": {"title": [{"plain_text": title}]},
        "Assign_new": {"multi_select": [{"name": n} for n in assignees]},
        "Status": {},
        "Заказчик_new": {},
        "Проект": {"relation": [{"id": pid} for pid in project_ids]},
        "Дата": {"date": {"start": due_start, "end": due_end} if due_start else None},
    }

    if status_type == "status":
        props["Status"] = {"status": {"name": status}}
    else:
        props["Status"] = {"select": {"name": status}}

    if reporter_type == "multi_select":
        props["Заказчик_new"] = {"multi_select": [{"name": n} for n in reporter]}
    else:
        props["Заказчик_new"] = {"select": {"name": reporter[0]} if reporter else None}

    return props


def test_basic_parse():
    raw = make_raw(props=make_props())
    result = parse(raw, DEFAULT_CONFIG)
    assert isinstance(result, TaskState)
    assert result.page_id == "page-1"
    assert result.title == "Task Name"
    assert "Alice" in result.assignees
    assert result.status == "В работе"


def test_status_type_status():
    raw = make_raw(props=make_props(status_type="status", status="Готово"))
    result = parse(raw, DEFAULT_CONFIG)
    assert result.status == "Готово"


def test_status_type_select():
    raw = make_raw(props=make_props(status_type="select", status="Сделать"))
    result = parse(raw, DEFAULT_CONFIG)
    assert result.status == "Сделать"


def test_reporter_multi_select():
    raw = make_raw(props=make_props(reporter_type="multi_select", reporter=("Charlie", "Dave")))
    result = parse(raw, DEFAULT_CONFIG)
    assert "Charlie" in result.reporter
    assert "Dave" in result.reporter


def test_reporter_select():
    raw = make_raw(props=make_props(reporter_type="select", reporter=("Eve",)))
    result = parse(raw, DEFAULT_CONFIG)
    assert "Eve" in result.reporter


def test_reporter_select_none():
    props = make_props()
    props["Заказчик_new"] = {"select": None}
    raw = make_raw(props=props)
    result = parse(raw, DEFAULT_CONFIG)
    assert result.reporter == frozenset()


def test_project_ids_parsed():
    raw = make_raw(props=make_props(project_ids=("proj-1", "proj-2")))
    result = parse(raw, DEFAULT_CONFIG)
    assert "proj-1" in result.project_ids
    assert "proj-2" in result.project_ids


def test_due_start_only():
    raw = make_raw(props=make_props(due_start="2024-05-10"))
    result = parse(raw, DEFAULT_CONFIG)
    assert result.due_start == "2024-05-10"
    assert result.due_end is None


def test_due_range():
    raw = make_raw(props=make_props(due_start="2024-05-10", due_end="2024-05-20"))
    result = parse(raw, DEFAULT_CONFIG)
    assert result.due_start == "2024-05-10"
    assert result.due_end == "2024-05-20"


def test_missing_property_fallback_no_exception(caplog):
    """Missing prop -> fallback, warn-once, no raise."""
    raw = make_raw(props={})  # empty props
    # Clear warn set so we get fresh warnings
    _warned_missing.clear()
    with caplog.at_level(logging.WARNING, logger="notify_bot.notion.parser"):
        result = parse(raw, DEFAULT_CONFIG)
    assert isinstance(result, TaskState)
    assert "missing property" in caplog.text


def test_missing_property_warn_once(caplog):
    """Warn only once per key across multiple parse calls."""
    _warned_missing.clear()
    raw = make_raw(props={})
    with caplog.at_level(logging.WARNING, logger="notify_bot.notion.parser"):
        parse(raw, DEFAULT_CONFIG)
        first_count = caplog.text.count("missing property")
        parse(raw, DEFAULT_CONFIG)
        second_count = caplog.text.count("missing property")
    # Second parse should not add more warnings for same keys
    assert second_count == first_count


def test_title_concatenated():
    props = make_props()
    props["Name"] = {"title": [{"plain_text": "Hello"}, {"plain_text": " World"}]}
    raw = make_raw(props=props)
    result = parse(raw, DEFAULT_CONFIG)
    assert result.title == "Hello World"


def test_empty_title():
    props = make_props()
    props["Name"] = {"title": []}
    raw = make_raw(props=props)
    result = parse(raw, DEFAULT_CONFIG)
    assert result.title == ""


def test_url_and_last_edited_time():
    raw = make_raw(
        url="https://www.notion.so/task-xyz",
        last_edited_time="2024-06-01T12:00:00Z",
        props=make_props(),
    )
    result = parse(raw, DEFAULT_CONFIG)
    assert result.url == "https://www.notion.so/task-xyz"
    assert result.last_edited_time == "2024-06-01T12:00:00Z"


def test_no_due_returns_none_none():
    props = make_props()
    props["Дата"] = {"date": None}
    raw = make_raw(props=props)
    result = parse(raw, DEFAULT_CONFIG)
    assert result.due_start is None
    assert result.due_end is None
