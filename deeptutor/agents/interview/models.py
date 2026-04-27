"""Data models for the mock interview agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ── State machine ──────────────────────────────────────────────────────


InterviewState = Literal[
    "idle",
    "questioning",
    "answering",
    "followup_questioning",
    "followup_answering",
    "scoring",
    "reviewing",
    "completed",
    "cancelled",
    "error",
]


# ── Scoring ────────────────────────────────────────────────────────────


@dataclass
class DimensionScore:
    """Score for a single rubric dimension."""

    dimension: str = ""
    score: float = 0.0
    max_score: float = 10.0
    deduction_reason: str = ""
    evidence: str = ""


# ── Interview Turn ─────────────────────────────────────────────────────


@dataclass
class InterviewTurn:
    """A single turn in the interview flow."""

    role: str = ""  # "system", "user", "interviewer", "examinee"
    content: str = ""
    turn_type: str = ""  # "question", "answer", "followup", "followup_answer", "score", "review"
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Interview Session ──────────────────────────────────────────────────


@dataclass
class InterviewSession:
    """Complete record of a single mock interview."""

    session_id: str = ""
    user_id: str = ""
    exam_type: str = ""
    position: str = ""
    question_type: str = ""
    difficulty: str = ""
    question_text: str = ""
    user_answer: str = ""
    followup_question: str = ""
    followup_answer: str = ""
    scores: list[DimensionScore] = field(default_factory=list)
    total_score: float = 0.0
    review_report: str = ""
    training_suggestion: str = ""
    turns: list[InterviewTurn] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "exam_type": self.exam_type,
            "position": self.position,
            "question_type": self.question_type,
            "difficulty": self.difficulty,
            "question_text": self.question_text,
            "user_answer": self.user_answer,
            "followup_question": self.followup_question,
            "followup_answer": self.followup_answer,
            "scores": [
                {
                    "dimension": s.dimension,
                    "score": s.score,
                    "max_score": s.max_score,
                    "deduction_reason": s.deduction_reason,
                    "evidence": s.evidence,
                }
                for s in self.scores
            ],
            "total_score": self.total_score,
            "review_report": self.review_report,
            "training_suggestion": self.training_suggestion,
            "turns": [
                {
                    "role": t.role,
                    "content": t.content,
                    "turn_type": t.turn_type,
                    "metadata": t.metadata,
                }
                for t in self.turns
            ],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterviewSession:
        scores = [
            DimensionScore(**s)
            for s in data.get("scores", [])
        ]
        turns = [
            InterviewTurn(**t)
            for t in data.get("turns", [])
        ]
        return cls(
            session_id=data.get("session_id", ""),
            user_id=data.get("user_id", ""),
            exam_type=data.get("exam_type", ""),
            position=data.get("position", ""),
            question_type=data.get("question_type", ""),
            difficulty=data.get("difficulty", ""),
            question_text=data.get("question_text", ""),
            user_answer=data.get("user_answer", ""),
            followup_question=data.get("followup_question", ""),
            followup_answer=data.get("followup_answer", ""),
            scores=scores,
            total_score=data.get("total_score", 0.0),
            review_report=data.get("review_report", ""),
            training_suggestion=data.get("training_suggestion", ""),
            turns=turns,
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            metadata=data.get("metadata", {}),
        )
