"""Router: map Events + bindings -> list[NotificationPlanItem].

Rules implemented:
  BR-5: one person in multiple roles per event -> deduplicated via chat_id set
  BR-6: unbound recipient -> log, skip
  Renderer is injected as a callable to keep this module pure.
"""

import logging
from collections.abc import Callable

from notify_bot.core.dedup import build_dedup_key
from notify_bot.core.models import (
    Event,
    EventKind,
    NotificationPlanItem,
    TaskState,
)

log = logging.getLogger(__name__)


def route(
    events: list,
    task: TaskState,
    bindings: dict,
    renderer: Callable,
    project_name: str | None = None,
    display_tz: str = "Europe/Moscow",
) -> list:
    """Map events to NotificationPlanItems.

    Args:
        events: list[Event] from differ.diff().
        task: current TaskState (used for assignees/reporter sets).
        bindings: dict mapping canonical_name -> chat_id (int or None).
        renderer: callable(event, task, project_name, tz) -> str (HTML text).
        project_name: resolved project name or None.
        display_tz: timezone name for date formatting.

    Returns:
        list[NotificationPlanItem]
    """
    plan = []

    for event in events:
        recipients, value = _recipients_and_value(event, task)
        chat_ids = _resolve_chat_ids(recipients, bindings, task.page_id)

        for chat_id in chat_ids:
            key = build_dedup_key(
                task.page_id, event.kind, value, task.last_edited_time, chat_id
            )
            text = renderer(event, task, project_name, display_tz)
            plan.append(NotificationPlanItem(chat_id=chat_id, text=text, dedup_key=key))

    return plan


def _recipients_and_value(event: Event, task: TaskState) -> tuple:
    """Return (recipient_name_set, dedup_value) for an event."""
    if event.kind == EventKind.NEW_ASSIGNEE:
        return {event.target_name}, event.target_name
    # STATUS_CHANGED: all assignees + reporter
    recipients = set(task.assignees) | set(task.reporter)
    return recipients, event.new_status


def _resolve_chat_ids(
    recipients: set, bindings: dict, page_id: str
) -> set:
    """Resolve names to chat_ids, logging unbound ones (BR-6)."""
    chat_ids = set()
    for name in recipients:
        chat_id = bindings.get(name)
        if chat_id is None:
            log.info("unbound_recipient name=%s page_id=%s", name, page_id)
            continue
        chat_ids.add(chat_id)
    return chat_ids
