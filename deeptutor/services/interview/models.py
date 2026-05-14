"""Data models for interview learner profile and memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "是"}
    return bool(value)


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_as_str(item) for item in value if item is not None]


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


# ── Learner Profile ────────────────────────────────────────────────────


@dataclass
class StableProfile:
    """Long-term stable information about a learner.

    These fields change slowly and should not be overwritten frequently.
    """

    target_exam_type: str = ""
    target_position: str = ""
    current_stage: str = ""
    training_preference: str = ""
    needs_template_prompt: bool = False
    needs_high_score_demo: bool = False
    updated_at: str = ""

    @classmethod
    def empty(cls) -> StableProfile:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StableProfile:
        return cls(
            target_exam_type=_as_str(data.get("target_exam_type")),
            target_position=_as_str(data.get("target_position")),
            current_stage=_as_str(data.get("current_stage")),
            training_preference=_as_str(data.get("training_preference")),
            needs_template_prompt=_as_bool(data.get("needs_template_prompt", False)),
            needs_high_score_demo=_as_bool(data.get("needs_high_score_demo", False)),
            updated_at=_as_str(data.get("updated_at")),
        )


@dataclass
class DynamicProfile:
    """Recent training status — changes frequently as the user trains."""

    recent_weak_types: list[str] = field(default_factory=list)
    recent_low_score_dimensions: list[dict[str, Any]] = field(default_factory=list)
    recent_deduction_reasons: list[str] = field(default_factory=list)
    recent_followup_issues: list[str] = field(default_factory=list)
    repeated_weak_dimensions: list[dict[str, Any]] = field(default_factory=list)
    resolved_dimensions: list[dict[str, Any]] = field(default_factory=list)
    dimension_trends: list[dict[str, Any]] = field(default_factory=list)
    training_suggestion_history: list[dict[str, Any]] = field(default_factory=list)
    current_training_suggestion: str = ""
    recent_trend: str = ""
    updated_at: str = ""

    @classmethod
    def empty(cls) -> DynamicProfile:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DynamicProfile:
        return cls(
            recent_weak_types=_as_str_list(data.get("recent_weak_types")),
            recent_low_score_dimensions=_as_dict_list(
                data.get("recent_low_score_dimensions")
            ),
            recent_deduction_reasons=_as_str_list(data.get("recent_deduction_reasons")),
            recent_followup_issues=_as_str_list(data.get("recent_followup_issues")),
            repeated_weak_dimensions=_as_dict_list(
                data.get("repeated_weak_dimensions")
            ),
            resolved_dimensions=_as_dict_list(data.get("resolved_dimensions")),
            dimension_trends=_as_dict_list(data.get("dimension_trends")),
            training_suggestion_history=_as_dict_list(
                data.get("training_suggestion_history")
            ),
            current_training_suggestion=_as_str(
                data.get("current_training_suggestion")
            ),
            recent_trend=_as_str(data.get("recent_trend")),
            updated_at=_as_str(data.get("updated_at")),
        )


@dataclass
class LearnerProfile:
    """Combined learner profile with stable + dynamic parts."""

    stable: StableProfile = field(default_factory=StableProfile.empty)
    dynamic: DynamicProfile = field(default_factory=DynamicProfile.empty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable": self.stable.to_dict(),
            "dynamic": self.dynamic.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearnerProfile:
        stable_data = data.get("stable", {})
        dynamic_data = data.get("dynamic", {})
        return cls(
            stable=StableProfile.from_dict(stable_data),
            dynamic=DynamicProfile.from_dict(dynamic_data),
        )

    @classmethod
    def empty(cls) -> LearnerProfile:
        return cls()


# ── Interview Session ──────────────────────────────────────────────────


@dataclass
class DimensionScore:
    """Score for a single rubric dimension."""

    dimension: str = ""
    score: float = 0.0
    max_score: float = 10.0
    deduction_reason: str = ""
    evidence: str = ""


@dataclass
class InterviewTurn:
    """A single turn in the interview (Q&A, followup, etc.)."""

    role: str = ""  # "system", "user", "interviewer", "examinee"
    content: str = ""
    turn_type: str = ""  # "question", "answer", "followup", "followup_answer", "score", "review"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InterviewSession:
    """Complete record of a single mock interview session."""

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
            "scores": [asdict(s) for s in self.scores],
            "total_score": self.total_score,
            "review_report": self.review_report,
            "training_suggestion": self.training_suggestion,
            "turns": [asdict(t) for t in self.turns],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterviewSession:
        scores = [DimensionScore(**s) for s in data.get("scores", [])]
        turns = [InterviewTurn(**t) for t in data.get("turns", [])]
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


@dataclass
class InterviewMemorySnapshot:
    """Complete snapshot of a user's interview memory."""

    profile: LearnerProfile = field(default_factory=LearnerProfile.empty)
    recent_sessions: list[InterviewSession] = field(default_factory=list)
    session_count: int = 0
    last_updated: str = ""
