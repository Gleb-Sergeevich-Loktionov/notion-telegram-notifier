"""Smoke test: every production module must import against real dependencies.

Catches dependency API drift (e.g. renamed aiogram exception classes) that
fake-based unit tests cannot see.
"""

import importlib
import pkgutil

import notify_bot


def test_all_modules_import() -> None:
    import main  # noqa: F401  (composition root)

    for module_info in pkgutil.walk_packages(notify_bot.__path__, "notify_bot."):
        if ".tests" in module_info.name:
            continue
        importlib.import_module(module_info.name)
