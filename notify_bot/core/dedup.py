"""Dedup key builder (CR-1).

Key format: {page_id}:{kind}:{value}:{last_edited_time}:{chat_id}

Including last_edited_time ensures legitimate re-occurrences of the same
business fact (name removed then re-added, task re-opened) are NOT
suppressed permanently.
"""

from notify_bot.core.models import EventKind


def build_dedup_key(
    page_id: str,
    kind: EventKind,
    value: str,
    last_edited_time: str,
    chat_id: int,
) -> str:
    """Build a dedup key for a notification.

    Args:
        page_id: Notion page UUID.
        kind: EventKind enum value.
        value: For NEW_ASSIGNEE — the assignee name.
               For STATUS_CHANGED — the new_status string.
        last_edited_time: ISO timestamp from Notion (CR-1: version token).
        chat_id: Telegram chat_id of recipient.
    """
    return f"{page_id}:{kind.value}:{value}:{last_edited_time}:{chat_id}"
