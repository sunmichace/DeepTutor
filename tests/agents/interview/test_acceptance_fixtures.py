"""Validation for mock interview acceptance fixtures."""

from __future__ import annotations

import json
from pathlib import Path


def test_interview_acceptance_cases_are_well_formed() -> None:
    path = Path("tests/fixtures/interview_acceptance_cases.json")
    cases = json.loads(path.read_text(encoding="utf-8"))

    assert len(cases) >= 5
    seen_ids: set[str] = set()
    required = {
        "id",
        "question_type",
        "position",
        "difficulty",
        "question",
        "sample_answer",
        "acceptance_checks",
    }
    for case in cases:
        assert required <= set(case)
        assert case["id"] not in seen_ids
        seen_ids.add(case["id"])
        assert case["question"].strip()
        assert len(case["sample_answer"]) >= 50
        assert isinstance(case["acceptance_checks"], list)
        assert len(case["acceptance_checks"]) >= 2
