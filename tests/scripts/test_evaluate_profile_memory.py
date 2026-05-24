from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_eval_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_profile_memory.py"
    spec = importlib.util.spec_from_file_location("evaluate_profile_memory_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_profile_eval_fixture_passes(tmp_path: Path):
    evaluator = _load_eval_module()

    result = await evaluator.run_eval(
        fixture=Path("tests/fixtures/profile_eval_cases.json"),
        runtime_root=tmp_path / "runtime",
    )

    assert result["total"] >= 2
    assert result["failed"] == 0
    assert result["passed"] == result["total"]
