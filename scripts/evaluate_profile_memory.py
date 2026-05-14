#!/usr/bin/env python3
"""Deterministic profile-memory quality evaluation for mock interview sessions."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from deeptutor.agents.interview.memory_writer import write_session_to_memory
from deeptutor.agents.interview.models import DimensionScore, InterviewSession
from deeptutor.services.interview.memory import InterviewMemoryService, reset_interview_memory_instances
from deeptutor.services.path_service import PathService


def _score_from_dict(item: dict[str, Any]) -> DimensionScore:
    return DimensionScore(
        dimension=str(item.get("dimension") or ""),
        score=float(item.get("score") or 0),
        max_score=float(item.get("max_score") or 10),
        deduction_reason=str(item.get("deduction_reason") or ""),
        evidence=str(item.get("evidence") or ""),
    )


def _session_from_dict(item: dict[str, Any], *, user_id: str) -> InterviewSession:
    return InterviewSession(
        session_id=str(item.get("session_id") or ""),
        user_id=user_id,
        exam_type=str(item.get("exam_type") or "公考面试"),
        position=str(item.get("position") or "综合管理"),
        question_type=str(item.get("question_type") or ""),
        difficulty=str(item.get("difficulty") or "medium"),
        total_score=float(item.get("total_score") or 0),
        completed_at=str(item.get("completed_at") or ""),
        training_suggestion=str(item.get("training_suggestion") or ""),
        scores=[
            _score_from_dict(score)
            for score in item.get("scores", [])
            if isinstance(score, dict)
        ],
    )


def _contains_all(actual: list[str], expected: list[str]) -> bool:
    return all(item in actual for item in expected)


def _evaluate_profile(profile: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    dynamic = profile.get("dynamic", {})

    actual_repeated = [
        str(item.get("dimension") or "")
        for item in dynamic.get("repeated_weak_dimensions", [])
        if isinstance(item, dict)
    ]
    expected_repeated = expected.get("repeated_weak_dimensions", [])
    if expected_repeated and not _contains_all(actual_repeated, expected_repeated):
        failures.append(
            f"repeated_weak_dimensions expected {expected_repeated}, got {actual_repeated}"
        )
    for excluded in expected.get("repeated_weak_dimensions_excludes", []):
        if excluded in actual_repeated:
            failures.append(
                f"repeated_weak_dimensions expected NOT to include {excluded!r}, got {actual_repeated}"
            )

    actual_weak_types = dynamic.get("recent_weak_types", [])
    expected_weak_types = expected.get("recent_weak_types", [])
    if expected_weak_types and not _contains_all(actual_weak_types, expected_weak_types):
        failures.append(f"recent_weak_types expected {expected_weak_types}, got {actual_weak_types}")
    for excluded in expected.get("recent_weak_types_excludes", []):
        if excluded in actual_weak_types:
            failures.append(
                f"recent_weak_types expected NOT to include {excluded!r}, got {actual_weak_types}"
            )

    actual_status = {
        str(item.get("dimension") or ""): str(item.get("status") or "")
        for item in dynamic.get("dimension_trends", [])
        if isinstance(item, dict)
    }
    for dimension, status in expected.get("dimension_status", {}).items():
        if actual_status.get(dimension) != status:
            failures.append(
                f"dimension_status[{dimension}] expected {status}, got {actual_status.get(dimension)}"
            )
    for dimension in expected.get("dimension_status_absent", []):
        if dimension in actual_status:
            failures.append(
                f"dimension_status expected NOT to include {dimension!r}, got {actual_status}"
            )

    latest = expected.get("latest_training_suggestion")
    if latest and dynamic.get("current_training_suggestion") != latest:
        failures.append(
            "current_training_suggestion expected "
            f"{latest!r}, got {dynamic.get('current_training_suggestion')!r}"
        )

    history_contains = expected.get("training_suggestion_history_contains", [])
    if history_contains:
        history = [
            str(item.get("suggestion") or "")
            for item in dynamic.get("training_suggestion_history", [])
            if isinstance(item, dict)
        ]
        for text in history_contains:
            if text not in history:
                failures.append(
                    f"training_suggestion_history expected to contain {text!r}, got {history}"
                )

    history_excludes = expected.get("training_suggestion_history_excludes", [])
    if history_excludes:
        history = [
            str(item.get("suggestion") or "")
            for item in dynamic.get("training_suggestion_history", [])
            if isinstance(item, dict)
        ]
        for text in history_excludes:
            if text in history:
                failures.append(
                    f"training_suggestion_history expected NOT to include {text!r}, got {history}"
                )

    expected_statuses = expected.get("training_suggestion_statuses", {})
    if expected_statuses:
        actual_statuses = {
            str(item.get("suggestion") or ""): str(item.get("status") or "")
            for item in dynamic.get("training_suggestion_history", [])
            if isinstance(item, dict)
        }
        for text, status in expected_statuses.items():
            if actual_statuses.get(text) != status:
                failures.append(
                    f"training_suggestion status for {text!r} expected {status!r}, "
                    f"got {actual_statuses.get(text)!r}"
                )

    expected_resolved = expected.get("resolved_dimensions", [])
    if expected_resolved:
        actual_resolved = [
            str(item.get("dimension") or "")
            for item in dynamic.get("resolved_dimensions", [])
            if isinstance(item, dict)
        ]
        if not _contains_all(actual_resolved, expected_resolved):
            failures.append(
                f"resolved_dimensions expected {expected_resolved}, got {actual_resolved}"
            )

    trend_contains = expected.get("recent_trend_contains")
    if trend_contains and trend_contains not in str(dynamic.get("recent_trend") or ""):
        failures.append(
            f"recent_trend expected to contain {trend_contains!r}, got {dynamic.get('recent_trend')!r}"
        )

    return failures


def _evaluate_picker(
    *,
    service: InterviewMemoryService,
    expected: dict[str, Any],
    requested_difficulty: str,
) -> list[str]:
    from deeptutor.agents.interview.picker import resolve_picker_hints

    if not any(
        key in expected
        for key in (
            "picker_focus_dimensions",
            "picker_focus_question_types",
            "picker_avoid_question_types",
            "picker_active_suggestion",
            "picker_suggested_difficulty",
        )
    ):
        return []

    hints = resolve_picker_hints(
        profile=service.read_profile(),
        recent_sessions=service.get_recent_sessions(limit=5),
        requested_difficulty=requested_difficulty,
    )

    failures: list[str] = []

    expected_focus = expected.get("picker_focus_dimensions")
    if expected_focus is not None and hints.focus_dimensions != list(expected_focus):
        failures.append(
            f"picker.focus_dimensions expected {expected_focus}, got {hints.focus_dimensions}"
        )

    expected_focus_qt = expected.get("picker_focus_question_types")
    if expected_focus_qt is not None and hints.focus_question_types != list(expected_focus_qt):
        failures.append(
            f"picker.focus_question_types expected {expected_focus_qt}, "
            f"got {hints.focus_question_types}"
        )

    expected_avoid = expected.get("picker_avoid_question_types")
    if expected_avoid is not None and hints.avoid_question_types != list(expected_avoid):
        failures.append(
            f"picker.avoid_question_types expected {expected_avoid}, "
            f"got {hints.avoid_question_types}"
        )

    expected_suggestion = expected.get("picker_active_suggestion")
    if expected_suggestion is not None and hints.active_suggestion != expected_suggestion:
        failures.append(
            f"picker.active_suggestion expected {expected_suggestion!r}, "
            f"got {hints.active_suggestion!r}"
        )

    expected_diff = expected.get("picker_suggested_difficulty")
    if expected_diff is not None and hints.suggested_difficulty != expected_diff:
        failures.append(
            f"picker.suggested_difficulty expected {expected_diff!r}, "
            f"got {hints.suggested_difficulty!r}"
        )

    return failures


async def _run_case(case: dict[str, Any], *, root: Path) -> dict[str, Any]:
    user_id = str(case.get("user_id") or case.get("id") or "profile-eval")
    service = InterviewMemoryService(user_id)
    for item in case.get("sessions", []):
        if isinstance(item, dict):
            await write_session_to_memory(
                session=_session_from_dict(item, user_id=user_id),
                memory_service=service,
            )

    expected = case.get("expected", {})
    profile = service.read_profile().to_dict()
    failures = _evaluate_profile(profile, expected)
    failures.extend(
        _evaluate_picker(
            service=service,
            expected=expected,
            requested_difficulty=str(case.get("requested_difficulty") or "medium"),
        )
    )
    return {
        "id": case.get("id") or user_id,
        "passed": not failures,
        "failures": failures,
        "profile": profile,
    }


async def run_eval(*, fixture: Path, runtime_root: Path) -> dict[str, Any]:
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("Profile eval fixture must be a list of cases.")

    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    reset_interview_memory_instances()
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)

    try:
        service._project_root = runtime_root
        service._user_data_dir = runtime_root / "data" / "user"
        results = [
            await _run_case(case, root=runtime_root)
            for case in cases
            if isinstance(case, dict)
        ]
    finally:
        reset_interview_memory_instances()
        service._project_root = original_root
        service._user_data_dir = original_user_dir

    passed = sum(1 for item in results if item["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate mock-interview profile memory quality.")
    parser.add_argument(
        "--fixture",
        default=str(_PROJECT_ROOT / "tests" / "fixtures" / "profile_eval_cases.json"),
    )
    parser.add_argument(
        "--runtime-root",
        default="/tmp/deeptutor-profile-eval",
        help="Temporary runtime root; will be recreated.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON result.")
    args = parser.parse_args()

    result = asyncio.run(
        run_eval(
            fixture=Path(args.fixture),
            runtime_root=Path(args.runtime_root),
        )
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"profile_eval: {result['passed']}/{result['total']} passed")
        for item in result["results"]:
            status = "PASS" if item["passed"] else "FAIL"
            print(f"{status} {item['id']}")
            for failure in item["failures"]:
                print(f"  - {failure}")
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
