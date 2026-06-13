"""Domain models for notify_bot.

All dataclasses are frozen (immutable). No external dependencies.
"""

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class TaskState:
    page_id: str
    title: str
    status: str | None
    assignees: frozenset  # frozenset[str]
    reporter: frozenset   # frozenset[str]
    project_ids: tuple    # tuple[str, ...]
    due_start: str | None  # ISO date
    due_end: str | None
    url: str
    last_edited_time: str  # ISO from Notion


class EventKind(str, Enum):
    NEW_ASSIGNEE = "new_assignee"
    STATUS_CHANGED = "status_changed"


@dataclass(frozen=True)
class Event:
    page_id: str
    kind: EventKind
    # NEW_ASSIGNEE: target_name set; STATUS_CHANGED: old_status/new_status set
    target_name: str | None = None
    old_status: str | None = None
    new_status: str | None = None


@dataclass(frozen=True)
class NotificationPlanItem:
    chat_id: int
    text: str
    dedup_key: str
