"""Tests for telegram/sender.py (spec §12).

Covers:
- success → True
- TelegramRetryAfter → sleep(retry_after) then retry → True
- TelegramRetryAfter → retry also fails → False
- TelegramForbiddenError → False, no raise
- TelegramBadRequest → False, no raise
"""

import asyncio
import pytest

from notify_bot.telegram import sender as sender_mod


# ── Fake bot helpers ─────────────────────────────────────────────────────────


class _FakeMethod:
    """Callable that records calls and optionally raises on call N."""

    def __init__(self, side_effects):
        # side_effects: list of Exception | None per sequential call
        self._effects = list(side_effects)
        self._call_idx = 0
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        effect = self._effects[self._call_idx] if self._call_idx < len(self._effects) else None
        self._call_idx += 1
        if effect is not None:
            raise effect


class FakeBot:
    def __init__(self, *side_effects):
        self._method = _FakeMethod(side_effects)

    async def send_message(self, **kwargs):
        return await self._method(**kwargs)

    @property
    def calls(self):
        return self._method.calls


def _retry_after_exc(seconds: int):
    """Build a TelegramRetryAfter with the given retry_after value."""
    from aiogram.exceptions import TelegramRetryAfter
    from unittest.mock import MagicMock
    return TelegramRetryAfter(method=MagicMock(), message="Flood control", retry_after=seconds)


def _forbidden_exc():
    from aiogram.exceptions import TelegramForbiddenError
    from unittest.mock import MagicMock
    return TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked")


def _bad_request_exc(message="Bad Request: message text is empty"):
    from aiogram.exceptions import TelegramBadRequest
    from unittest.mock import MagicMock
    return TelegramBadRequest(method=MagicMock(), message=message)


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_success_returns_true():
    """Successful send_message returns True."""
    bot = FakeBot(None)  # no exception
    result = await sender_mod.send(bot, chat_id=123, text="hello")
    assert result is True
    assert len(bot.calls) == 1
    assert bot.calls[0]["chat_id"] == 123
    assert bot.calls[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_send_forbidden_returns_false(monkeypatch):
    """TelegramForbiddenError → False, does not propagate."""
    bot = FakeBot(_forbidden_exc())
    result = await sender_mod.send(bot, chat_id=42, text="hi")
    assert result is False


@pytest.mark.asyncio
async def test_send_bad_request_returns_false():
    """TelegramBadRequest → False, does not propagate."""
    bot = FakeBot(_bad_request_exc())
    result = await sender_mod.send(bot, chat_id=42, text="hi")
    assert result is False


@pytest.mark.asyncio
async def test_send_retry_after_sleeps_and_retries(monkeypatch):
    """TelegramRetryAfter → sleep(retry_after) → retry succeeds → True."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(sender_mod.asyncio, "sleep", fake_sleep)

    exc = _retry_after_exc(7)
    bot = FakeBot(exc, None)  # first call raises, second succeeds
    result = await sender_mod.send(bot, chat_id=99, text="msg")

    assert result is True
    assert slept == [7]
    assert len(bot.calls) == 2  # tried twice


@pytest.mark.asyncio
async def test_send_retry_after_retry_also_fails(monkeypatch):
    """TelegramRetryAfter → sleep → retry also fails → False (not raised)."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(sender_mod.asyncio, "sleep", fake_sleep)

    exc = _retry_after_exc(3)
    bot = FakeBot(exc, _bad_request_exc())  # first: rate-limited, second: bad request
    result = await sender_mod.send(bot, chat_id=77, text="txt")

    assert result is False
    assert slept == [3]


@pytest.mark.asyncio
async def test_send_uses_html_parse_mode():
    """send() always uses ParseMode.HTML and disable_web_page_preview=True."""
    from aiogram.enums import ParseMode
    bot = FakeBot(None)
    await sender_mod.send(bot, chat_id=1, text="<b>bold</b>")
    kw = bot.calls[0]
    assert kw.get("parse_mode") == ParseMode.HTML
    assert kw.get("disable_web_page_preview") is True
