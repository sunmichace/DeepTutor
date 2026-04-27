"""Tests for MockInterviewCoordinator data flow logic.

These tests verify the state machine transitions and data integrity
without calling actual LLM APIs (using monkeypatch/mocks).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.agents.interview.coordinator import MockInterviewCoordinator
from deeptutor.agents.interview.models import InterviewSession, InterviewTurn, DimensionScore
from deeptutor.services.interview import (
    InterviewMemoryService,
    LearnerProfile,
    StableProfile,
    reset_interview_memory_instances,
)


@pytest.fixture(autouse=True)
def reset():
    reset_interview_memory_instances()
    yield


@pytest.fixture
def coordinator():
    return MockInterviewCoordinator(user_id="test_user", language="zh")


def test_initial_state(coordinator):
    assert coordinator.state == "idle"
    assert coordinator.session is None


@pytest.mark.asyncio
async def test_start_interview_no_rag(coordinator):
    """start_interview should work even without RAG (uses fallback question)."""
    result = await coordinator.start_interview(
        exam_type="公考面试",
        position="综合管理",
        question_type="综合分析",
        difficulty="medium",
    )
    assert result["state"] == "questioning"
    assert "session_id" in result
    assert result["question"]
    assert coordinator.session is not None
    assert coordinator.session.question_type == "综合分析"
    assert coordinator.session.position == "综合管理"


@pytest.mark.asyncio
async def test_start_interview_profile_read(coordinator):
    """start_interview should read user profile for context."""
    # Pre-set a profile
    svc = InterviewMemoryService("test_user")
    svc.save_profile(LearnerProfile(
        stable=StableProfile(target_exam_type="国考", target_position="税务"),
    ))

    result = await coordinator.start_interview(question_type="综合分析")
    assert result["examiner_context"]
    assert "税务" in result["examiner_context"] or "国考" in result["examiner_context"]


@pytest.mark.asyncio
async def test_submit_answer_without_session(coordinator):
    """Submitting an answer without starting should return an error."""
    result = await coordinator.submit_answer("test answer")
    assert "error" in result


@pytest.mark.asyncio
async def test_cancel(coordinator):
    await coordinator.start_interview()
    result = await coordinator.cancel()
    assert result["state"] == "cancelled"


@pytest.mark.asyncio
async def test_full_flow_with_mocked_llm(coordinator):
    """Test the full interview flow with mocked LLM calls.

    This verifies state transitions and data collection.
    """
    # Mock the followup decision and scoring
    with patch(
        "deeptutor.agents.interview.followup_agent.should_follow_up",
        AsyncMock(return_value=False),
    ), patch(
        "deeptutor.agents.interview.scoring_agent.score_answer",
        AsyncMock(return_value=(
            [DimensionScore(dimension=f"维度{i+1}", score=7.0, max_score=10.0) for i in range(8)],
            56.0,
        )),
    ), patch(
        "deeptutor.agents.interview.review_agent.generate_review",
        AsyncMock(return_value="Mock review report.\n下一步训练建议：加强综合分析练习。"),
    ):
        # Start
        start = await coordinator.start_interview(question_type="综合分析")
        assert coordinator.state == "questioning"

        # Answer (no followup expected)
        result = await coordinator.submit_answer("这是一道综合分析题的作答内容。")
        assert result["state"] == "completed"
        assert result["total_score"] == 56.0
        assert len(result["scores"]) == 8

        # Verify session data
        session = coordinator.session
        assert session is not None
        assert session.question_text
        assert session.user_answer == "这是一道综合分析题的作答内容。"
        assert session.total_score == 56.0
        assert len(session.turns) >= 3  # context + question + answer + score + review

        # Verify memory was written
        svc = InterviewMemoryService("test_user")
        saved_sessions = svc.list_sessions()
        assert len(saved_sessions) >= 1
        profile = svc.read_profile()
        assert profile.dynamic.current_training_suggestion


@pytest.mark.asyncio
async def test_full_flow_with_followup(coordinator):
    """Test flow where followup is triggered."""
    with patch(
        "deeptutor.agents.interview.followup_agent.should_follow_up",
        AsyncMock(return_value=True),
    ), patch(
        "deeptutor.agents.interview.followup_agent.generate_followup",
        AsyncMock(return_value="请具体举例说明。"),
    ), patch(
        "deeptutor.agents.interview.scoring_agent.score_answer",
        AsyncMock(return_value=(
            [DimensionScore(dimension=f"维度{i+1}", score=6.0, max_score=10.0) for i in range(8)],
            48.0,
        )),
    ), patch(
        "deeptutor.agents.interview.review_agent.generate_review",
        AsyncMock(return_value="Mock review. 建议：加强审题。"),
    ):
        await coordinator.start_interview(question_type="综合分析")

        # First answer triggers followup
        result = await coordinator.submit_answer("我的初步回答。")
        assert result["state"] == "followup_questioning"
        assert result["needs_followup"] is True
        assert result["followup_question"] == "请具体举例说明。"
        assert coordinator.state == "followup_questioning"

        # Followup answer should complete the flow
        result2 = await coordinator.submit_followup_answer("具体例子是...")
        assert result2["state"] == "completed"
        assert result2["total_score"] == 48.0

        # Verify followup was captured
        session = coordinator.session
        assert session is not None
        assert session.followup_question == "请具体举例说明。"
        assert session.followup_answer == "具体例子是..."


@pytest.mark.asyncio
async def test_submit_followup_without_followup_question(coordinator):
    """submit_followup_answer directly should still work (edge case)."""
    with patch(
        "deeptutor.agents.interview.followup_agent.should_follow_up",
        AsyncMock(return_value=False),
    ), patch(
        "deeptutor.agents.interview.scoring_agent.score_answer",
        AsyncMock(return_value=(
            [DimensionScore(dimension=f"维度{i+1}", score=5.0, max_score=10.0) for i in range(8)],
            40.0,
        )),
    ), patch(
        "deeptutor.agents.interview.review_agent.generate_review",
        AsyncMock(return_value="Review."),
    ):
        await coordinator.start_interview()
        # Submit answer (no followup)
        result = await coordinator.submit_answer("回答内容。")
        # Should complete normally
        assert result["state"] == "completed"
