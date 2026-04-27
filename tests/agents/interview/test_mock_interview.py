"""Basic tests for MockInterviewCoordinator — state flow without LLM calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.agents.interview.coordinator import MockInterviewCoordinator
from deeptutor.services.interview import InterviewMemoryService, reset_interview_memory_instances


@pytest.fixture(autouse=True)
def reset():
    reset_interview_memory_instances()
    yield


@pytest.mark.asyncio
async def test_coordinator_initial_state() -> None:
    """Coordinator starts in idle state."""
    coord = MockInterviewCoordinator(user_id="test_user")
    assert coord.state == "idle"
    assert coord.session is None


@pytest.mark.asyncio
async def test_cancel_without_start() -> None:
    """Cancel before starting should still work."""
    coord = MockInterviewCoordinator(user_id="test_user")
    result = await coord.cancel()
    assert result["state"] == "cancelled"


@pytest.mark.asyncio
async def test_submit_answer_without_session() -> None:
    """Submitting answer without active session returns error."""
    coord = MockInterviewCoordinator(user_id="test_user")
    result = await coord.submit_answer("test answer")
    assert "error" in result


@pytest.mark.asyncio
@patch.object(InterviewMemoryService, "get_recent_sessions", return_value=[])
async def test_start_interview_creates_session(mock_get) -> None:
    """Start interview creates a session with question."""
    coord = MockInterviewCoordinator(user_id="test_user")
    result = await coord.start_interview(
        exam_type="公考面试",
        position="税务",
        question_type="综合分析",
        difficulty="medium",
    )

    assert result["state"] == "questioning"
    assert "session_id" in result
    assert result["question"]
    assert coord.session is not None
    assert coord.session.exam_type == "公考面试"
    assert coord.session.position == "税务"
    assert coord.session.question_type == "综合分析"


@pytest.mark.asyncio
@patch.object(InterviewMemoryService, "get_recent_sessions", return_value=[])
async def test_start_interview_twice_creates_new_session(mock_get) -> None:
    """Starting a second interview creates a new session."""
    coord = MockInterviewCoordinator(user_id="test_user")
    r1 = await coord.start_interview()
    r2 = await coord.start_interview()
    assert r1["session_id"] != r2["session_id"]
    assert coord.session is not None
    assert coord.session.session_id == r2["session_id"]
