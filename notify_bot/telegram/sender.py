"""Send a notification message to a Telegram chat.

Spec §12 (locked):
- HTML parse_mode, disable_web_page_preview=True
- TelegramRetryAfter: sleep(retry_after + 1) then retry once
- TelegramForbiddenError / TelegramBadRequest: warn + return False
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.enums import ParseMode

import asyncio

log = logging.getLogger(__name__)


async def send(bot: Bot, chat_id: int, text: str) -> bool:
    """Send HTML message to chat_id. Returns True on success, False on permanent failure."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except TelegramRetryAfter as exc:
        wait = exc.retry_after
        log.warning("sender: rate limited chat_id=%s, waiting %ss", chat_id, wait)
        await asyncio.sleep(wait)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except Exception as retry_exc:
            log.warning("sender: retry failed chat_id=%s: %s", chat_id, retry_exc)
            return False
    except TelegramForbiddenError:
        log.warning("sender: bot blocked by chat_id=%s", chat_id)
        return False
    except TelegramBadRequest as exc:
        log.warning("sender: bad request chat_id=%s: %s", chat_id, exc)
        return False
