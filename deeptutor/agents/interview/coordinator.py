"""MockInterviewCoordinator — orchestrates the full mock interview flow.

State machine:
  IDLE -> QUESTIONING -> ANSWERING ->
    [FOLLOWUP_QUESTION -> FOLLOWUP_ANSWERING]* ->
    SCORING -> REVIEWING -> COMPLETED

P0 constraints:
  - Max 1 followup round
  - Text-only (no audio)
  - Topics selected from the interview knowledge base (RAG)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from deeptutor.logging import Logger, get_logger
from deeptutor.services.interview import InterviewMemoryService, get_interview_memory_service
from deeptutor.services.rag.service import RAGService

from .context_builder import (
    build_examinee_context,
    build_interviewer_context,
    build_review_context,
    build_scoring_context,
)
from .followup_agent import generate_followup, should_follow_up
from .memory_writer import write_session_to_memory
from .models import (
    DimensionScore,
    InterviewSession,
    InterviewState,
    InterviewTurn,
)
from .review_agent import generate_review
from .scoring_agent import score_answer

logger: Logger = get_logger("MockInterviewCoordinator")

_INTERVIEW_KB = "interview_bank"

_RUBRIC_DIMENSIONS = [
    "审题与立意",
    "结构化表达",
    "逻辑完整性",
    "论据与案例质量",
    "岗位匹配度",
    "语言自然度",
    "临场应对",
    "追问应答质量",
]


class MockInterviewCoordinator:
    """Orchestrate a complete mock interview session."""

    def __init__(
        self,
        user_id: str = "default",
        language: str = "zh",
        memory_service: InterviewMemoryService | None = None,
        rag_service: RAGService | None = None,
    ) -> None:
        self._user_id = user_id
        self._language = language
        self._memory = memory_service or get_interview_memory_service(user_id)
        self._rag = rag_service or RAGService()
        self._state: InterviewState = "idle"
        self._session: InterviewSession | None = None

    @property
    def state(self) -> InterviewState:
        return self._state

    @property
    def session(self) -> InterviewSession | None:
        return self._session

    # ── Public flow ────────────────────────────────────────────────────

    async def start_interview(
        self,
        *,
        exam_type: str = "公考面试",
        position: str = "",
        question_type: str = "综合分析",
        difficulty: str = "medium",
    ) -> dict[str, Any]:
        """Start a new mock interview: select question, build context."""
        self._state = "questioning"
        session_id = str(uuid4())

        # 1. Fetch a question from the interview knowledge base
        question_text = await self._select_question(
            question_type=question_type,
            difficulty=difficulty,
            position=position,
        )

        # 2. Read learner profile for context
        profile = self._memory.read_profile()
        recent = self._memory.get_recent_sessions(limit=5)

        # 3. Build examiner context
        examiner_context = build_interviewer_context(
            profile=profile,
            recent_sessions=recent,
            question_type=question_type,
        )

        self._session = InterviewSession(
            session_id=session_id,
            user_id=self._user_id,
            exam_type=exam_type,
            position=position,
            question_type=question_type,
            difficulty=difficulty,
            question_text=question_text,
            started_at=datetime.now().astimezone().isoformat(),
        )

        self._session.turns.append(
            InterviewTurn(
                role="system",
                content=examiner_context,
                turn_type="context",
            )
        )
        self._session.turns.append(
            InterviewTurn(
                role="interviewer",
                content=question_text,
                turn_type="question",
            )
        )

        return {
            "session_id": session_id,
            "question": question_text,
            "state": self._state,
            "examiner_context": examiner_context,
        }

    async def submit_answer(self, answer: str) -> dict[str, Any]:
        """Process the examinee's answer to the main question."""
        if not self._session:
            return {"error": "No active interview session"}

        self._session.user_answer = answer
        self._session.turns.append(
            InterviewTurn(role="examinee", content=answer, turn_type="answer")
        )

        # Check if follow-up is needed
        profile = self._memory.read_profile()
        needs_followup = await should_follow_up(
            question=self._session.question_text,
            answer=answer,
            weak_points=profile.dynamic.recent_weak_types if profile else None,
            language=self._language,
        )

        if needs_followup:
            self._state = "followup_questioning"
            followup_q = await generate_followup(
                question=self._session.question_text,
                answer=answer,
                question_type=self._session.question_type,
                position=self._session.position,
                weak_points=profile.dynamic.recent_weak_types if profile else None,
                language=self._language,
            )
            self._session.followup_question = followup_q
            self._session.turns.append(
                InterviewTurn(
                    role="interviewer",
                    content=followup_q,
                    turn_type="followup",
                )
            )
            return {
                "state": self._state,
                "followup_question": followup_q,
                "needs_followup": True,
            }

        # No followup — go straight to scoring
        return await self._score_and_review()

    async def submit_followup_answer(self, answer: str) -> dict[str, Any]:
        """Process the examinee's answer to the follow-up question."""
        if not self._session:
            return {"error": "No active interview session"}

        self._session.followup_answer = answer
        self._session.turns.append(
            InterviewTurn(
                role="examinee", content=answer, turn_type="followup_answer"
            )
        )

        return await self._score_and_review()

    async def cancel(self) -> dict[str, Any]:
        """Cancel the current interview."""
        self._state = "cancelled"
        return {"state": self._state, "message": "Interview cancelled"}

    # ── Internal flow ──────────────────────────────────────────────────

    async def _score_and_review(self) -> dict[str, Any]:
        """Score the session, generate review, and persist to memory."""
        if not self._session:
            return {"error": "No active interview session"}

        self._state = "scoring"

        # 1. Score the answer
        scores, total = await score_answer(
            question=self._session.question_text,
            answer=self._session.user_answer,
            followup_question=self._session.followup_question,
            followup_answer=self._session.followup_answer,
            question_type=self._session.question_type,
            position=self._session.position,
            language=self._language,
        )
        self._session.scores = scores
        self._session.total_score = total
        self._session.turns.append(
            InterviewTurn(
                role="system",
                content=json.dumps(
                    {
                        "scores": [
                            {
                                "dimension": s.dimension,
                                "score": s.score,
                                "deduction_reason": s.deduction_reason,
                            }
                            for s in scores
                        ],
                        "total_score": total,
                    },
                    ensure_ascii=False,
                ),
                turn_type="score",
            )
        )

        # 2. Generate review
        self._state = "reviewing"
        previous_sessions = self._memory.get_recent_sessions(limit=5)
        profile = self._memory.read_profile()

        review_text = await generate_review(
            session=self._session,
            previous_sessions=previous_sessions,
            language=self._language,
        )
        self._session.review_report = review_text

        # Extract training suggestion (first substantive line after "下一步训练建议")
        self._session.training_suggestion = _extract_training_suggestion(review_text)
        self._session.turns.append(
            InterviewTurn(
                role="system",
                content=review_text,
                turn_type="review",
            )
        )

        # 3. Mark completed
        self._state = "completed"
        self._session.completed_at = datetime.now().astimezone().isoformat()

        # 4. Persist to memory
        await write_session_to_memory(
            session=self._session,
            memory_service=self._memory,
        )

        return {
            "state": self._state,
            "session_id": self._session.session_id,
            "scores": [
                {
                    "dimension": s.dimension,
                    "score": s.score,
                    "max_score": s.max_score,
                    "deduction_reason": s.deduction_reason,
                    "evidence": s.evidence,
                }
                for s in scores
            ],
            "total_score": total,
            "review": review_text,
            "training_suggestion": self._session.training_suggestion,
        }

    async def _select_question(
        self,
        *,
        question_type: str,
        difficulty: str,
        position: str,
    ) -> str:
        """Select a question from the interview knowledge base via RAG."""
        query = f"{question_type} 面试题 {' '.join(filter(None, [position, difficulty]))}"
        try:
            result = await self._rag.search(
                query=query,
                kb_name=_INTERVIEW_KB,
            )
            content = str(result.get("content", "") or result.get("answer", "") or "")
            if content.strip():
                return content.strip()[:2000]  # cap length
        except Exception as exc:
            logger.warning(f"RAG question selection failed, using fallback: {exc}")

        # Fallback question if RAG is unavailable
        return (
            f"请谈谈你对'{question_type}'这一类面试题的理解。"
            f"你认为回答这类题目时最重要的是什么？"
            f"请结合你的岗位方向({position or '通用'})进行说明。"
        )


def _extract_training_suggestion(review_text: str) -> str:
    """Extract the training suggestion from a review report."""
    import re

    # Look for "下一步训练建议" section
    match = re.search(
        r"(?:下一步训练建议|训练建议|建议)[：:]\s*(.*?)(?:\n\n|\Z)",
        review_text,
        re.DOTALL,
    )
    if match:
        suggestion = match.group(1).strip().split("\n")[0]
        return suggestion[:200]

    # Fallback: last non-empty line
    lines = [l.strip() for l in review_text.split("\n") if l.strip()]
    return lines[-1][:200] if lines else ""
