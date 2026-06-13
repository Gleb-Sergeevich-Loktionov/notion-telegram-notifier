"""Tests for core/dedup.py — CR-1 and functional matrix."""

from notify_bot.core.dedup import build_dedup_key
from notify_bot.core.models import EventKind


def test_key_format_new_assignee():
    key = build_dedup_key("page1", EventKind.NEW_ASSIGNEE, "Alice", "2024-01-01T10:00:00Z", 123)
    assert key == "page1:new_assignee:Alice:2024-01-01T10:00:00Z:123"


def test_key_format_status_changed():
    key = build_dedup_key("page1", EventKind.STATUS_CHANGED, "Готово", "2024-01-01T10:00:00Z", 456)
    assert key == "page1:status_changed:Готово:2024-01-01T10:00:00Z:456"


def test_same_observation_same_let_same_key():
    """Same page+kind+value+let+chat_id -> identical key (dedup works)."""
    k1 = build_dedup_key("p", EventKind.NEW_ASSIGNEE, "Bob", "2024-01-01T00:00:00Z", 99)
    k2 = build_dedup_key("p", EventKind.NEW_ASSIGNEE, "Bob", "2024-01-01T00:00:00Z", 99)
    assert k1 == k2


def test_different_let_different_key_cr1():
    """CR-1: new last_edited_time -> different key -> NOT deduped."""
    k1 = build_dedup_key("p", EventKind.NEW_ASSIGNEE, "Bob", "2024-01-01T00:00:00Z", 99)
    k2 = build_dedup_key("p", EventKind.NEW_ASSIGNEE, "Bob", "2024-02-01T00:00:00Z", 99)
    assert k1 != k2


def test_different_chat_id_different_key():
    k1 = build_dedup_key("p", EventKind.NEW_ASSIGNEE, "Alice", "2024-01-01T00:00:00Z", 1)
    k2 = build_dedup_key("p", EventKind.NEW_ASSIGNEE, "Alice", "2024-01-01T00:00:00Z", 2)
    assert k1 != k2


def test_different_page_different_key():
    k1 = build_dedup_key("p1", EventKind.STATUS_CHANGED, "Готово", "2024-01-01T00:00:00Z", 1)
    k2 = build_dedup_key("p2", EventKind.STATUS_CHANGED, "Готово", "2024-01-01T00:00:00Z", 1)
    assert k1 != k2


def test_different_kind_different_key():
    k1 = build_dedup_key("p", EventKind.NEW_ASSIGNEE, "Alice", "2024-01-01T00:00:00Z", 1)
    k2 = build_dedup_key("p", EventKind.STATUS_CHANGED, "Alice", "2024-01-01T00:00:00Z", 1)
    assert k1 != k2
