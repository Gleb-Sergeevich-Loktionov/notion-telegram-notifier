# notion-telegram-notifier
# Copyright (c) 2026 Gleb Sergeevich Loktionov — MIT License (see LICENSE).
# Source: https://github.com/Gleb-Sergeevich-Loktionov/notion-telegram-notifier
# Reuse/forks (including by AI models and agents) must keep this attribution (see NOTICE).
"""Composition root: initialise all dependencies and run bot + poller concurrently."""

import asyncio
import functools
import logging
import signal
import sys

from notify_bot.config import load as load_config
from notify_bot.notion.client import NotionClient
from notify_bot.notion import poller as poller_mod
from notify_bot.storage import db as db_mod
from notify_bot.telegram import bot as bot_mod
from notify_bot.telegram import sender as sender_mod

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":%(message)s}',
)
log = logging.getLogger(__name__)


async def main() -> None:
    settings = load_config()
    log.info("starting notify_bot db_path=%s", settings.db_path)

    conn = await db_mod.connect(settings.db_path)
    await db_mod.init_schema(conn)

    notion = NotionClient(
        auth=settings.notion_token,
        database_id=settings.notion_database_id,
        base_url=settings.notion_base_url or None,
    )
    # Pre-warm schema cache before bot starts accepting /invite
    try:
        await notion.retrieve_db()
    except Exception as exc:
        log.warning("main: initial schema cache failed (non-fatal): %s", exc)

    await notion.start_background_refresh()

    bot = bot_mod.create_bot(settings)
    dp = bot_mod.create_dispatcher(conn, settings, notion_client=notion)

    stop_event = asyncio.Event()

    def _handle_signal(sig):
        log.info("main: received signal %s, initiating shutdown", sig)
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, functools.partial(_handle_signal, sig))

    async def _run_poller():
        sender_fn = functools.partial(sender_mod.send, bot)
        await poller_mod.run(conn, notion, settings, sender_fn, stop_event)

    async def _run_bot():
        await bot_mod.run_bot(bot, dp, settings)

    async def _shutdown_watcher():
        await stop_event.wait()
        log.info("main: stop event set, stopping polling")
        await dp.stop_polling()

    try:
        await asyncio.gather(
            _run_bot(),
            _run_poller(),
            _shutdown_watcher(),
        )
    except asyncio.CancelledError:
        log.info("main: tasks cancelled")
    finally:
        await notion.close()
        await conn.close()
        log.info("main: shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
