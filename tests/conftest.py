"""Shared pytest configuration for the DeepTutor test suite."""

from __future__ import annotations

import asyncio
import inspect
import importlib.util
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run tests that call live external services.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "asyncio: run an async test function")
    config.addinivalue_line("markers", "live: calls live external services")
    config.addinivalue_line("markers", "flaky(reruns): documents expected live-test variance")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live"):
        return

    skip_live = pytest.mark.skip(reason="requires --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


if importlib.util.find_spec("pytest_asyncio") is None:

    _ASYNC_FALLBACK_PATHS = (
        "/tests/agents/interview/",
        "/tests/services/interview/",
        "/tests/services/test_rag_manifest_fallback.py",
        "/tests/scripts/",
    )

    def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
        """Minimal asyncio test runner when pytest-asyncio is unavailable."""
        if "asyncio" not in pyfuncitem.keywords:
            return None
        test_path = pyfuncitem.path.as_posix()
        if not any(path in test_path for path in _ASYNC_FALLBACK_PATHS):
            return None

        test_function = pyfuncitem.obj
        if not inspect.iscoroutinefunction(test_function):
            return None

        fixture_names = pyfuncitem._fixtureinfo.argnames
        kwargs: dict[str, Any] = {
            name: pyfuncitem.funcargs[name]
            for name in fixture_names
            if name in pyfuncitem.funcargs
        }
        asyncio.run(test_function(**kwargs))
        return True
