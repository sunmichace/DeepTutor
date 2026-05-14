"""Local pytest config for RAG integration tests.

Hosts ``pytest_addoption`` for ``--pipeline``. It used to live inside
``test_pipeline_integration.py``, but pytest ≥ 7 only recognises the hook
from ``conftest.py`` / plugins, so the option was silently dropped.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--pipeline",
        action="store",
        default="llamaindex",
        help="Pipeline to test (or 'all' for all pipelines).",
    )
