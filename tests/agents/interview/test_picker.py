from __future__ import annotations

from deeptutor.agents.interview.models import DimensionScore, InterviewSession
from deeptutor.agents.interview.picker import (
    build_query_with_hints,
    filter_and_rerank,
    resolve_picker_hints,
)
from deeptutor.services.interview import DynamicProfile, LearnerProfile, StableProfile


def _session(total: float, *, sid: str = "s", dims: list[DimensionScore] | None = None) -> InterviewSession:
    return InterviewSession(
        session_id=sid,
        user_id="u",
        exam_type="公考面试",
        position="综合管理",
        question_type="综合分析",
        difficulty="medium",
        total_score=total,
        completed_at="2026-05-01T10:00:00+08:00",
        scores=dims or [],
    )


def test_resolve_picker_hints_empty_profile_is_cold_start():
    hints = resolve_picker_hints(
        profile=LearnerProfile(stable=StableProfile(), dynamic=DynamicProfile()),
        recent_sessions=[],
        requested_difficulty="medium",
    )
    assert hints.focus_dimensions == []
    assert hints.focus_question_types == []
    assert hints.avoid_question_types == []
    assert hints.active_suggestion == ""
    assert hints.suggested_difficulty == "medium"
    assert hints.reason == "cold_start"


def test_resolve_picker_hints_surfaces_repeated_weak_and_active_suggestion():
    dynamic = DynamicProfile(
        repeated_weak_dimensions=[
            {"dimension": "论据与案例质量", "count": 3},
            {"dimension": "结构化表达", "count": 2},
        ],
        recent_weak_types=["综合分析", "社会现象"],
        resolved_dimensions=[
            {"dimension": "语言自然度", "question_types": ["岗位匹配"]},
        ],
        training_suggestion_history=[
            {"suggestion": "加强论据深度。", "status": "active"},
            {"suggestion": "练习结构化分层。", "status": "expired"},
        ],
    )
    hints = resolve_picker_hints(
        profile=LearnerProfile(dynamic=dynamic),
        recent_sessions=[],
        requested_difficulty="medium",
    )
    assert hints.focus_dimensions == ["论据与案例质量", "结构化表达"]
    assert hints.focus_question_types == ["综合分析", "社会现象"]
    assert hints.avoid_question_types == ["岗位匹配"]
    assert hints.active_suggestion == "加强论据深度。"
    assert hints.suggested_difficulty == "medium"
    assert "focus_dim" in hints.reason


def test_resolve_picker_hints_steps_difficulty_up_when_recent_avg_high():
    sessions = [_session(78, sid="a"), _session(74, sid="b"), _session(80, sid="c")]
    hints = resolve_picker_hints(
        profile=LearnerProfile(),
        recent_sessions=sessions,
        requested_difficulty="medium",
    )
    assert hints.suggested_difficulty == "hard"
    assert "diff=medium->hard" in hints.reason


def test_resolve_picker_hints_steps_difficulty_down_when_recent_avg_low():
    sessions = [_session(45, sid="a"), _session(42, sid="b"), _session(38, sid="c")]
    hints = resolve_picker_hints(
        profile=LearnerProfile(),
        recent_sessions=sessions,
        requested_difficulty="medium",
    )
    assert hints.suggested_difficulty == "easy"
    assert "diff=medium->easy" in hints.reason


def test_resolve_picker_hints_does_not_step_when_caller_requested_hard():
    sessions = [_session(45), _session(40), _session(38)]
    hints = resolve_picker_hints(
        profile=LearnerProfile(),
        recent_sessions=sessions,
        requested_difficulty="hard",
    )
    assert hints.suggested_difficulty == "hard"


def test_resolve_picker_hints_requires_three_scored_sessions_to_step():
    sessions = [_session(78, sid="a"), _session(80, sid="b")]
    hints = resolve_picker_hints(
        profile=LearnerProfile(),
        recent_sessions=sessions,
        requested_difficulty="medium",
    )
    assert hints.suggested_difficulty == "medium"


def test_build_query_with_hints_augments_with_focus_and_suggestion():
    hints = resolve_picker_hints(
        profile=LearnerProfile(
            dynamic=DynamicProfile(
                repeated_weak_dimensions=[{"dimension": "论据与案例质量", "count": 2}],
                training_suggestion_history=[
                    {"suggestion": "按题型整理两个可复用案例，练 STAR 结构。", "status": "active"},
                ],
            )
        ),
        recent_sessions=[],
        requested_difficulty="medium",
    )
    query = build_query_with_hints(
        question_type="综合分析",
        difficulty="medium",
        position="公务员",
        hints=hints,
    )
    assert "综合分析" in query
    assert "论据与案例质量" in query
    # suggestion is truncated to 40 chars; it should fit without mangling.
    assert "按题型整理两个可复用案例" in query


def test_build_query_with_hints_no_profile_matches_baseline():
    hints = resolve_picker_hints(
        profile=LearnerProfile(),
        recent_sessions=[],
        requested_difficulty="medium",
    )
    query = build_query_with_hints(
        question_type="综合分析",
        difficulty="medium",
        position="公务员",
        hints=hints,
    )
    assert query == "综合分析 面试题 公务员 medium"


def test_filter_and_rerank_bonuses_focus_and_matched_difficulty():
    hints = resolve_picker_hints(
        profile=LearnerProfile(
            dynamic=DynamicProfile(
                recent_weak_types=["社会现象"],
                resolved_dimensions=[{"question_types": ["岗位匹配"]}],
            )
        ),
        recent_sessions=[],
        requested_difficulty="medium",
    )
    manifest_index = {
        "社会现象真题.pdf": {
            "estimated_question_type": "社会现象",
            "estimated_difficulty": "medium",
        },
        "岗位匹配示范.pdf": {
            "estimated_question_type": "岗位匹配",
            "estimated_difficulty": "medium",
        },
        "通用模块.pdf": {
            "estimated_question_type": "基础",
            "estimated_difficulty": "easy",
        },
    }
    sources = [
        {"title": "通用模块.pdf", "score": 0.8},
        {"title": "岗位匹配示范.pdf", "score": 0.75},
        {"title": "社会现象真题.pdf", "score": 0.70},
    ]
    reranked = filter_and_rerank(
        sources=sources,
        hints=hints,
        manifest_index=manifest_index,
        requested_difficulty="medium",
    )
    # Focus match (+0.15) + diff match (+0.10) lifts 社会现象 above 通用.
    assert [s["title"] for s in reranked][0] == "社会现象真题.pdf"
    # Avoided question type is penalised and should not lead.
    assert reranked[-1]["title"] == "岗位匹配示范.pdf"


def test_filter_and_rerank_empty_sources_returns_unchanged():
    hints = resolve_picker_hints(
        profile=LearnerProfile(),
        recent_sessions=[],
        requested_difficulty="medium",
    )
    assert filter_and_rerank(sources=[], hints=hints, manifest_index={}, requested_difficulty="medium") == []


def test_filter_and_rerank_preserves_order_when_no_hints():
    hints = resolve_picker_hints(
        profile=LearnerProfile(),
        recent_sessions=[],
        requested_difficulty="medium",
    )
    sources = [
        {"title": "a.pdf", "score": 0.9},
        {"title": "b.pdf", "score": 0.8},
        {"title": "c.pdf", "score": 0.7},
    ]
    reranked = filter_and_rerank(
        sources=sources,
        hints=hints,
        manifest_index={},
        requested_difficulty="medium",
    )
    assert [s["title"] for s in reranked] == ["a.pdf", "b.pdf", "c.pdf"]
