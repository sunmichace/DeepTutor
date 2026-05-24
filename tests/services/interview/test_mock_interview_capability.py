"""Capability-level tests for mock interview session continuity."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from deeptutor.capabilities.mock_interview import MockInterviewCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.services.interview import reset_interview_memory_instances
from deeptutor.services.interview.models import LearnerProfile, StableProfile
from deeptutor.services.interview.memory import InterviewMemoryService
from deeptutor.services.path_service import PathService


async def _collect_events(run_coro) -> list[StreamEvent]:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await run_coro(bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer
    return events


@pytest.mark.asyncio
async def test_mock_interview_answer_restores_active_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    reset_interview_memory_instances()

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        monkeypatch.setattr(
            "deeptutor.agents.interview.coordinator.should_follow_up",
            AsyncMock(return_value=False),
        )
        monkeypatch.setattr(
            "deeptutor.agents.interview.coordinator.score_answer",
            AsyncMock(return_value=([], 60.0)),
        )
        monkeypatch.setattr(
            "deeptutor.agents.interview.coordinator.generate_review",
            AsyncMock(return_value="复盘报告。\n下一步训练建议：继续练习综合分析。"),
        )

        capability = MockInterviewCapability()
        start_context = UnifiedContext(
            session_id="user-session-1",
            language="zh",
            config_overrides={"mode": "start", "question_type": "综合分析"},
        )
        await _collect_events(lambda bus: capability.run(start_context, bus))

        active_path = tmp_path / "data" / "interview" / "user-session-1" / "active_session.json"
        assert active_path.exists()

        answer_context = UnifiedContext(
            session_id="user-session-1",
            user_message="我的作答内容。",
            language="zh",
            config_overrides={"mode": "answer"},
        )
        events = await _collect_events(lambda bus: capability.run(answer_context, bus))

        results: list[dict[str, Any]] = [
            event.metadata
            for event in events
            if event.type == StreamEventType.RESULT
        ]
        assert results[-1]["state"] == "completed"
        assert results[-1]["total_score"] == 60.0
        assert not active_path.exists()
    finally:
        reset_interview_memory_instances()
        service._project_root = original_root
        service._user_data_dir = original_user_dir


@pytest.mark.asyncio
async def test_mock_interview_followup_answer_restores_active_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    reset_interview_memory_instances()

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        monkeypatch.setattr(
            "deeptutor.agents.interview.coordinator.should_follow_up",
            AsyncMock(return_value=True),
        )
        monkeypatch.setattr(
            "deeptutor.agents.interview.coordinator.generate_followup",
            AsyncMock(return_value="请补充一个具体案例。"),
        )
        monkeypatch.setattr(
            "deeptutor.agents.interview.coordinator.score_answer",
            AsyncMock(return_value=([], 52.0)),
        )
        monkeypatch.setattr(
            "deeptutor.agents.interview.coordinator.generate_review",
            AsyncMock(return_value="复盘报告。\n下一步训练建议：补充案例。"),
        )

        capability = MockInterviewCapability()
        start_context = UnifiedContext(
            session_id="user-session-followup",
            language="zh",
            config_overrides={"mode": "start"},
        )
        await _collect_events(lambda bus: capability.run(start_context, bus))

        first_answer_context = UnifiedContext(
            session_id="user-session-followup",
            user_message="我的初步作答。",
            language="zh",
            config_overrides={"mode": "answer"},
        )
        first_events = await _collect_events(
            lambda bus: capability.run(first_answer_context, bus)
        )
        first_results = [
            event.metadata
            for event in first_events
            if event.type == StreamEventType.RESULT
        ]
        assert first_results[-1]["state"] == "followup_questioning"

        active_path = (
            tmp_path
            / "data"
            / "interview"
            / "user-session-followup"
            / "active_session.json"
        )
        assert "请补充一个具体案例。" in active_path.read_text(encoding="utf-8")

        followup_context = UnifiedContext(
            session_id="user-session-followup",
            user_message="具体案例是基层窗口服务。",
            language="zh",
            config_overrides={"mode": "answer"},
        )
        followup_events = await _collect_events(
            lambda bus: capability.run(followup_context, bus)
        )
        followup_results = [
            event.metadata
            for event in followup_events
            if event.type == StreamEventType.RESULT
        ]
        assert followup_results[-1]["state"] == "completed"
        assert followup_results[-1]["total_score"] == 52.0
        assert not active_path.exists()
    finally:
        reset_interview_memory_instances()
        service._project_root = original_root
        service._user_data_dir = original_user_dir


@pytest.mark.asyncio
async def test_mock_interview_profile_mode_returns_structured_snapshot(tmp_path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    reset_interview_memory_instances()

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"
        InterviewMemoryService("profile-user").save_profile(
            LearnerProfile(stable=StableProfile(target_exam_type="国考"))
        )

        capability = MockInterviewCapability()
        context = UnifiedContext(
            session_id="profile-user",
            language="zh",
            config_overrides={"mode": "profile"},
        )
        events = await _collect_events(lambda bus: capability.run(context, bus))
        results = [
            event.metadata
            for event in events
            if event.type == StreamEventType.RESULT
        ]

        assert results[-1]["mode"] == "profile"
        assert results[-1]["profile"]["stable"]["target_exam_type"] == "国考"
        assert results[-1]["sessions"] == []
        assert '"target_exam_type": "国考"' in results[-1]["response"]
    finally:
        reset_interview_memory_instances()
        service._project_root = original_root
        service._user_data_dir = original_user_dir
