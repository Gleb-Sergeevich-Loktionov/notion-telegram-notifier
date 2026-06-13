"""Middleware: AdminFilter silences non-admin messages without reply (T-5)."""

from typing import Any, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message


class AdminFilter(BaseMiddleware):
    """Only allow messages from admin chat IDs to pass through."""

    def __init__(self, admin_chat_ids: tuple) -> None:
        self._admin_ids: frozenset = frozenset(admin_chat_ids)

    async def __call__(
        self,
        handler: Callable,
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is None or user.id not in self._admin_ids:
            return  # silence — no reply
        return await handler(event, data)
