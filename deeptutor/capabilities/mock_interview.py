"""Mock Interview Capability — conducts a full mock interview flow.

Flow:
  1. User chooses exam type, position, question type, difficulty
  2. System selects question from interview knowledge base
  3. User answers
  4. System optionally generates follow-up question
  5. User answers follow-up
  6. System scores answer against 8 rubric dimensions
  7. System generates review report
  8. Results are persisted to the user's learner profile

P0: text-only, max 1 followup round.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.capabilities.request_contracts import get_capability_request_schema
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus


class MockInterviewCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="mock_interview",
        description="Full mock interview: question → answer → followup → scoring → review → memory.",
        stages=["questioning", "answering", "followup", "scoring", "reviewing"],
        tools_used=["rag"],
        cli_aliases=["interview", "mock"],
        request_schema=get_capability_request_schema("mock_interview"),
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        from deeptutor.agents.interview.coordinator import MockInterviewCoordinator
        from deeptutor.services.interview import get_interview_memory_service

        user_id = context.session_id or "default"
        overrides = context.config_overrides or {}
        mode = str(overrides.get("mode", "start") or "start").strip().lower()
        language = context.language or "zh"

        memory_service = get_interview_memory_service(user_id=user_id)
        coordinator = MockInterviewCoordinator(
            user_id=user_id,
            language=language,
            memory_service=memory_service,
        )

        if mode == "start":
            async with stream.stage("questioning", source=self.name):
                await stream.thinking("正在准备面试题目...", source=self.name, stage="questioning")

                result = await coordinator.start_interview(
                    exam_type=str(overrides.get("exam_type", "公考面试")),
                    position=str(overrides.get("position", "")),
                    question_type=str(overrides.get("question_type", "综合分析")),
                    difficulty=str(overrides.get("difficulty", "medium")),
                )

                await stream.content(
                    f"**题目：**\n{result.get('question', '')}",
                    source=self.name,
                    stage="questioning",
                )
                await stream.result(
                    {
                        "response": result.get("question", ""),
                        "session_id": result.get("session_id", ""),
                        "mode": "start",
                        "state": result.get("state", "questioning"),
                    },
                    source=self.name,
                )

        elif mode == "answer":
            answer = context.user_message or str(overrides.get("answer", "") or "")
            active_session = memory_service.read_active_session()
            if active_session is not None:
                coordinator.restore_session(active_session)

            async with stream.stage("answering", source=self.name):
                await stream.thinking("正在评估作答...", source=self.name, stage="answering")

                followup_phase = coordinator.state in ("followup_questioning",)

                if followup_phase:
                    result = await coordinator.submit_followup_answer(answer)
                else:
                    result = await coordinator.submit_answer(answer)

                state = result.get("state", "")
                if state == "followup_questioning":
                    await stream.content(
                        f"**追问：**\n{result.get('followup_question', '')}",
                        source=self.name,
                        stage="followup",
                    )
                    await stream.result(
                        {
                            "response": result.get("followup_question", ""),
                            "state": state,
                            "needs_followup": True,
                        },
                        source=self.name,
                    )
                elif state == "completed":
                    scores = result.get("scores", [])
                    scores_text = "\n".join(
                        f"- {s['dimension']}: {s['score']}/{s['max_score']}"
                        + (f"（{s['deduction_reason']}）" if s.get("deduction_reason") else "")
                        for s in scores
                    )
                    await stream.content(
                        f"**评分结果：**\n总分：{result.get('total_score', 0)}/80\n\n{scores_text}",
                        source=self.name,
                        stage="scoring",
                    )
                    await stream.content(
                        f"**复盘报告：**\n{result.get('review', '')}",
                        source=self.name,
                        stage="reviewing",
                    )
                    await stream.result(
                        {
                            "response": result.get("review", ""),
                            "session_id": result.get("session_id", ""),
                            "scores": result.get("scores", []),
                            "total_score": result.get("total_score", 0),
                            "training_suggestion": result.get("training_suggestion", ""),
                            "state": "completed",
                            "mode": "answer",
                        },
                        source=self.name,
                    )
                else:
                    await stream.result(
                        {"response": "", "state": state},
                        source=self.name,
                    )

        elif mode == "cancel":
            result = await coordinator.cancel()
            await stream.result(
                {"response": "面试已取消", "state": result.get("state", "cancelled")},
                source=self.name,
            )

        elif mode == "profile":
            snapshot = memory_service.export_all()
            response = json.dumps(snapshot, ensure_ascii=False, indent=2)
            await stream.result(
                {
                    "response": response,
                    "mode": "profile",
                    "profile": snapshot.get("profile", {}),
                    "active_session": snapshot.get("active_session"),
                    "sessions": snapshot.get("sessions", []),
                },
                source=self.name,
            )
