"""Differ: compute Events from old vs new TaskState.

Rules implemented:
  BR-8: cold_start -> no events
  BR-4: DONE_STATUS gates NEW_ASSIGNEE
  HR-1: removed assignees are NOT events
"""

from notify_bot.core.models import Event, EventKind, TaskState

DEFAULT_DONE_STATUS = "Готово"


def diff(
    old: TaskState | None,
    new: TaskState,
    *,
    cold_start: bool,
    done_status: str = DEFAULT_DONE_STATUS,
) -> list:
    """Return list[Event] describing changes from old to new.

    Args:
        old: previous snapshot, or None if page never seen before.
        new: current page state.
        cold_start: True on first run (no checkpoint) — no events emitted.
        done_status: status string that suppresses NEW_ASSIGNEE (BR-4).
    """
    if cold_start:
        return []

    if old is None:
        return _diff_new_page(new, done_status)

    return _diff_existing_page(old, new, done_status)


def _diff_new_page(new: TaskState, done_status: str) -> list:
    """Generate events for a page never seen before by the bot."""
    if new.status == done_status or not new.assignees:
        return []

    return [
        Event(new.page_id, EventKind.NEW_ASSIGNEE, target_name=name)
        for name in new.assignees
    ]


def _diff_existing_page(old: TaskState, new: TaskState, done_status: str) -> list:
    """Generate events for a page that was already in snapshots."""
    events = []

    added = new.assignees - old.assignees
    if new.status != done_status:
        for name in added:
            events.append(Event(new.page_id, EventKind.NEW_ASSIGNEE, target_name=name))

    # Status change: any transition where new.status is not None
    if new.status != old.status and new.status is not None:
        events.append(
            Event(
                new.page_id,
                EventKind.STATUS_CHANGED,
                old_status=old.status,
                new_status=new.status,
            )
        )

    return events
