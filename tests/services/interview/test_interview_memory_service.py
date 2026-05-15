"""Tests for InterviewMemoryService — user isolation, CRUD, profile."""

from __future__ import annotations

from datetime import datetime

import pytest

from deeptutor.services.interview import (
    DynamicProfile,
    InterviewMemoryService,
    LearnerProfile,
    StableProfile,
    get_interview_memory_service,
    reset_interview_memory_instances,
)
from deeptutor.services.interview.models import DimensionScore, InterviewSession
from deeptutor.services.interview.memory import _PROFILE_FILE
from deeptutor.services.path_service import get_path_service


@pytest.fixture(autouse=True)
def reset():
    reset_interview_memory_instances()
    yield


def _root():
    return get_path_service().project_root / "data" / "interview"


def test_user_isolation() -> None:
    """User A and User B have separate profiles and sessions."""
    svc_a = InterviewMemoryService(user_id="user_a")
    svc_b = InterviewMemoryService(user_id="user_b")

    # Write profile for user_a only
    svc_a.save_profile(LearnerProfile(
        stable=StableProfile(target_exam_type="国考", target_position="税务"),
    ))

    # User B should have empty profile
    profile_b = svc_b.read_profile()
    assert profile_b.stable.target_exam_type == ""
    assert profile_b.stable.target_position == ""

    # User A should have their profile
    profile_a = svc_a.read_profile()
    assert profile_a.stable.target_exam_type == "国考"
    assert profile_a.stable.target_position == "税务"


def test_shared_instance() -> None:
    """get_interview_memory_service returns the same instance for the same user."""
    s1 = get_interview_memory_service("shared_test")
    s2 = get_interview_memory_service("shared_test")
    assert s1 is s2

    s3 = get_interview_memory_service("other_user")
    assert s1 is not s3


def test_save_and_read_profile() -> None:
    svc = InterviewMemoryService("profile_test")

    profile = LearnerProfile(
        stable=StableProfile(
            target_exam_type="省考",
            target_position="综合管理",
            current_stage="冲刺阶段",
            training_preference="真题训练",
            needs_template_prompt=True,
            needs_high_score_demo=False,
        ),
        dynamic=DynamicProfile(
            recent_weak_types=["综合分析", "计划组织"],
            current_training_suggestion="加强综合分析题练习",
        ),
    )

    svc.save_profile(profile)
    loaded = svc.read_profile()

    assert loaded.stable.target_exam_type == "省考"
    assert loaded.stable.target_position == "综合管理"
    assert loaded.stable.current_stage == "冲刺阶段"
    assert loaded.stable.training_preference == "真题训练"
    assert loaded.stable.needs_template_prompt is True
    assert loaded.stable.needs_high_score_demo is False
    assert loaded.dynamic.recent_weak_types == ["综合分析", "计划组织"]
    assert loaded.dynamic.current_training_suggestion == "加强综合分析题练习"


def test_profile_from_dict_preserves_field_types() -> None:
    profile = LearnerProfile.from_dict(
        {
            "stable": {
                "target_exam_type": "国考",
                "needs_template_prompt": True,
                "needs_high_score_demo": "false",
            },
            "dynamic": {
                "recent_weak_types": ["综合分析", 123],
                "recent_low_score_dimensions": [
                    {"dimension": "逻辑完整性", "score": 4},
                    "bad-item",
                ],
                "repeated_weak_dimensions": [
                    {"dimension": "逻辑完整性", "count": 2},
                    "bad-item",
                ],
                "dimension_trends": [
                    {"dimension": "逻辑完整性", "status": "declining"},
                    "bad-item",
                ],
                "training_suggestion_history": [
                    {"session_id": "s1", "suggestion": "补充案例"},
                    "bad-item",
                ],
                "recent_deduction_reasons": "not-a-list",
                "current_training_suggestion": None,
            },
        }
    )

    assert profile.stable.target_exam_type == "国考"
    assert profile.stable.needs_template_prompt is True
    assert profile.stable.needs_high_score_demo is False
    assert profile.dynamic.recent_weak_types == ["综合分析", "123"]
    assert profile.dynamic.recent_low_score_dimensions == [
        {"dimension": "逻辑完整性", "score": 4}
    ]
    assert profile.dynamic.repeated_weak_dimensions == [
        {"dimension": "逻辑完整性", "count": 2}
    ]
    assert profile.dynamic.dimension_trends == [
        {"dimension": "逻辑完整性", "status": "declining"}
    ]
    assert profile.dynamic.training_suggestion_history == [
        {"session_id": "s1", "suggestion": "补充案例"}
    ]
    assert profile.dynamic.recent_deduction_reasons == []
    assert profile.dynamic.current_training_suggestion == ""


def test_read_profile_empty() -> None:
    svc = InterviewMemoryService("nonexistent_user")
    profile = svc.read_profile()
    assert profile.stable.target_exam_type == ""
    assert profile.dynamic.recent_weak_types == []


def test_update_stable_profile() -> None:
    svc = InterviewMemoryService("update_test")
    svc.update_stable_profile(target_exam_type="国考")
    profile = svc.read_profile()
    assert profile.stable.target_exam_type == "国考"


def test_update_dynamic_profile() -> None:
    svc = InterviewMemoryService("dynamic_update")
    svc.update_dynamic_profile(recent_weak_types=["综合分析"])
    profile = svc.read_profile()
    assert profile.dynamic.recent_weak_types == ["综合分析"]


def test_clear_profile() -> None:
    svc = InterviewMemoryService("clear_test")
    svc.save_profile(LearnerProfile(
        stable=StableProfile(target_exam_type="国考"),
    ))
    assert svc.read_profile().stable.target_exam_type == "国考"

    svc.clear_profile()
    assert svc.read_profile().stable.target_exam_type == ""


def test_save_and_list_sessions() -> None:
    svc = InterviewMemoryService("session_test")
    now = "2026-04-27T12:00:00"

    s1 = InterviewSession(
        session_id="sess_001",
        user_id="session_test",
        question_type="综合分析",
        difficulty="medium",
        total_score=65.0,
        completed_at=now,
        scores=[DimensionScore(dimension="审题与立意", score=8.0, max_score=10.0)],
    )
    s2 = InterviewSession(
        session_id="sess_002",
        user_id="session_test",
        question_type="计划组织",
        difficulty="hard",
        total_score=55.0,
        completed_at=now,
    )

    svc.save_session(s1)
    svc.save_session(s2)

    sessions = svc.list_sessions()
    assert len(sessions) == 2

    filtered = svc.list_sessions(question_type="综合分析")
    assert len(filtered) == 1
    assert filtered[0]["session_id"] == "sess_001"


def test_read_session() -> None:
    svc = InterviewMemoryService("read_session_test")
    s = InterviewSession(session_id="sess_003", user_id="read_session_test")
    svc.save_session(s)

    loaded = svc.read_session("sess_003")
    assert loaded is not None
    assert loaded.session_id == "sess_003"
    assert loaded.user_id == "read_session_test"

    assert svc.read_session("nonexistent") is None


def test_save_and_read_session_preserves_picker_snapshot() -> None:
    """Regression: services/interview's InterviewSession used to drop the
    picker_snapshot field on persistence because it was only declared on the
    agents/interview copy of the class. Both classes must round-trip it."""
    svc = InterviewMemoryService("picker_snapshot_persistence_test")
    snapshot = {
        "hints": {
            "focus_dimensions": ["论据与案例质量"],
            "reason": "focus_dim=...",
        },
        "requested_difficulty": "medium",
        "effective_difficulty": "hard",
        "source_kind": "rag",
        "reranked_sources": [{"title": "x.pdf", "score": 0.71}],
        "query": "综合分析 面试题 公务员 hard 论据与案例质量",
    }
    s = InterviewSession(
        session_id="sess_picker_001",
        user_id="picker_snapshot_persistence_test",
        picker_snapshot=snapshot,
    )
    svc.save_session(s)

    loaded = svc.read_session("sess_picker_001")
    assert loaded is not None
    assert loaded.picker_snapshot == snapshot

    # Active-session round-trip must also preserve it.
    svc.save_active_session(s)
    active = svc.read_active_session()
    assert active is not None
    assert active.picker_snapshot == snapshot


def test_session_from_dict_defaults_missing_picker_snapshot() -> None:
    """Legacy session JSON files (pre-picker_snapshot) must still load."""
    legacy = {"session_id": "legacy_sess", "user_id": "legacy_user"}
    restored = InterviewSession.from_dict(legacy)
    assert restored.picker_snapshot == {}


def test_delete_session() -> None:
    svc = InterviewMemoryService("delete_test")
    s = InterviewSession(session_id="sess_004", user_id="delete_test")
    svc.save_session(s)

    assert svc.read_session("sess_004") is not None
    assert svc.delete_session("sess_004") is True
    assert svc.read_session("sess_004") is None
    assert svc.delete_session("nonexistent") is False


def test_clear_all_sessions() -> None:
    svc = InterviewMemoryService("clear_all_test")
    svc.save_session(InterviewSession(session_id="s1", user_id="clear_all_test"))
    svc.save_session(InterviewSession(session_id="s2", user_id="clear_all_test"))

    assert svc.count_sessions() == 2
    svc.clear_all_sessions()
    assert svc.count_sessions() == 0


def test_clear_all() -> None:
    svc = InterviewMemoryService("nuke_test")
    svc.save_profile(LearnerProfile(stable=StableProfile(target_exam_type="国考")))
    svc.save_session(InterviewSession(session_id="s1", user_id="nuke_test"))

    assert svc.read_profile().stable.target_exam_type == "国考"
    assert svc.count_sessions() == 1

    svc.clear_all()
    assert svc.read_profile().stable.target_exam_type == ""
    assert svc.count_sessions() == 0


def test_export_all() -> None:
    svc = InterviewMemoryService("export_test")
    svc.save_profile(LearnerProfile(stable=StableProfile(target_exam_type="国考")))
    svc.save_session(InterviewSession(session_id="s1", user_id="export_test"))

    exported = svc.export_all()
    assert exported["user_id"] == "export_test"
    assert exported["profile"]["stable"]["target_exam_type"] == "国考"
    assert len(exported["sessions"]) == 1


def test_storage_path_isolation() -> None:
    """Verify that different users write to different directories."""
    svc_a = InterviewMemoryService("path_a")
    svc_b = InterviewMemoryService("path_b")

    profile_a = LearnerProfile(stable=StableProfile(target_exam_type="国考"))
    svc_a.save_profile(profile_a)

    root = _root()
    assert (root / "path_a" / _PROFILE_FILE).exists()
    assert not (root / "path_b" / _PROFILE_FILE).exists()
