"""Tests for telegram/sender.py — retry, forbidden, bad request paths."""

# NOTE: This module patches aiogram Bot.send_message via a fake bot object;
# no real network calls are made.

import asyncio
import pytest

from notify_bot.telegram import sender as sender_mod


class FakeBot:
    def __init__(self, behaviors):
        """behaviors: list of callables or values; each call pops the next."""
        self._behaviors = list(behaviors)
        self.calls = 0

    async def send_message(self, **kwargs):
        self.calls += 1
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


@pytest.mark.asyncio
async def test_send_success_first_try():
    bot = FakeBot(["ok"])
    result = await sender_mod.send(bot, 123, "hi")
    assert result is True
    assert bot.calls == 1


@pytest.mark.asyncio
async def test_send_forbidden_returns_false():
    from aiogram.exceptions import TelegramForbiddenError
    exc = TelegramForbiddenError.__new__(TelegramForbiddenError)
    exc.message = "blocked"
    bot = FakeBot([exc])
    result = await sender_mod.send(bot, 123, "hi")
    assert result is False


@pytest.mark.asyncio
async def test_send_bad_request_returns_false():
    from aiogram.exceptions import TelegramBadRequest
    exc = TelegramBadRequest.__new__(TelegramBadRequest)
    exc.message = "bad"
    bot = FakeBot([exc])
    result = await sender_mod.send(bot, 123, "hi")
    assert result is False


@pytest.mark.asyncio
async def test_send_retry_after_then_success(monkeypatch):
    from aiogram.exceptions import TelegramRetryAfter

    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    exc = TelegramRetryAfter.__new__(TelegramRetryAfter)
    exc.retry_after = 3
    bot = FakeBot([exc, "ok"])
    result = await sender_mod.send(bot, 123, "hi")
    assert result is True
    assert bot.calls == 2
    assert slept == [3]


@pytest.mark.asyncio
async def test_send_retry_after_then_fail(monkeypatch):
    from aiogram.exceptions import TelegramRetryAfter

    async def fake_sleep(s):
        pass

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    exc = TelegramRetryAfter.__new__(TelegramRetryAfter)
    exc.retry_after = 1
    bot = FakeBot([exc, RuntimeError("still failing")])
    result = await sender_mod.send(bot, 123, "hi")
    assert result is False
    assert bot.calls == 2
