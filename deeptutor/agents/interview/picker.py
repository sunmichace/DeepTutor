"""Interview question picker — derives profile-based hints for RAG retrieval.

Pure data layer: takes a LearnerProfile + recent sessions and produces a
PickerHints record. No RAG calls, no LLM calls. The coordinator owns how
the hints flow into query construction and source re-ranking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deeptutor.services.interview import LearnerProfile

from .models import InterviewSession


@dataclass
class PickerHints:
    """Derived signals used to bias the next question selection.

    All fields default to empty / unchanged so that callers can use the
    object even when the user has no profile yet (cold start).
    """

    focus_dimensions: list[str] = field(default_factory=list)
    focus_question_types: list[str] = field(default_factory=list)
    avoid_question_types: list[str] = field(default_factory=list)
    active_suggestion: str = ""
    suggested_difficulty: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "focus_dimensions": list(self.focus_dimensions),
            "focus_question_types": list(self.focus_question_types),
            "avoid_question_types": list(self.avoid_question_types),
            "active_suggestion": self.active_suggestion,
            "suggested_difficulty": self.suggested_difficulty,
            "reason": self.reason,
        }


_MAX_FOCUS_DIMS = 2
_MAX_FOCUS_TYPES = 3
_MAX_SUGGESTION_QUERY_LEN = 40


def resolve_picker_hints(
    *,
    profile: LearnerProfile,
    recent_sessions: list[InterviewSession],
    requested_difficulty: str = "medium",
) -> PickerHints:
    """Build PickerHints from the learner profile and recent sessions."""
    dynamic = profile.dynamic

    focus_dimensions: list[str] = []
    for item in dynamic.repeated_weak_dimensions[:_MAX_FOCUS_DIMS]:
        name = str(item.get("dimension") or "").strip()
        if name:
            focus_dimensions.append(name)

    focus_question_types = [
        qt for qt in dynamic.recent_weak_types[:_MAX_FOCUS_TYPES] if qt
    ]

    avoid_question_types: list[str] = []
    for item in dynamic.resolved_dimensions:
        for qt in item.get("question_types") or []:
            qt_text = str(qt).strip()
            if qt_text and qt_text not in avoid_question_types:
                avoid_question_types.append(qt_text)

    active_suggestion = ""
    for item in dynamic.training_suggestion_history:
        if str(item.get("status") or "") == "active":
            active_suggestion = str(item.get("suggestion") or "").strip()
            break
    if not active_suggestion:
        active_suggestion = (dynamic.current_training_suggestion or "").strip()

    suggested_difficulty = _difficulty_from_recent_scores(
        recent_sessions=recent_sessions,
        requested_difficulty=requested_difficulty,
    )

    reason = _build_reason(
        focus_dimensions=focus_dimensions,
        focus_question_types=focus_question_types,
        avoid_question_types=avoid_question_types,
        suggested_difficulty=suggested_difficulty,
        requested_difficulty=requested_difficulty,
    )

    return PickerHints(
        focus_dimensions=focus_dimensions,
        focus_question_types=focus_question_types,
        avoid_question_types=avoid_question_types,
        active_suggestion=active_suggestion,
        suggested_difficulty=suggested_difficulty,
        reason=reason,
    )


def _difficulty_from_recent_scores(
    *,
    recent_sessions: list[InterviewSession],
    requested_difficulty: str,
) -> str:
    """Step difficulty up or down based on the last 3 sessions' average score.

    Only nudges when the caller passed the default "medium". Never skips
    a level; if data is insufficient, returns the requested value.
    """
    requested = (requested_difficulty or "").strip().lower()
    if requested != "medium":
        return requested_difficulty

    scored = [s for s in recent_sessions if (s.total_score or 0) > 0]
    if len(scored) < 3:
        return requested_difficulty

    last_three = scored[:3]
    avg = sum(float(s.total_score) for s in last_three) / 3.0
    if avg >= 70:
        return "hard"
    if avg <= 50:
        return "easy"
    return "medium"


def _build_reason(
    *,
    focus_dimensions: list[str],
    focus_question_types: list[str],
    avoid_question_types: list[str],
    suggested_difficulty: str,
    requested_difficulty: str,
) -> str:
    parts: list[str] = []
    if focus_dimensions:
        parts.append(f"focus_dim={','.join(focus_dimensions)}")
    if focus_question_types:
        parts.append(f"focus_qt={','.join(focus_question_types)}")
    if avoid_question_types:
        parts.append(f"avoid_qt={','.join(avoid_question_types)}")
    if suggested_difficulty and suggested_difficulty != requested_difficulty:
        parts.append(f"diff={requested_difficulty}->{suggested_difficulty}")
    if not parts:
        return "cold_start"
    return " ".join(parts)


def build_query_with_hints(
    *,
    question_type: str,
    difficulty: str,
    position: str,
    hints: PickerHints,
) -> str:
    """Augment the RAG query with the top focus dimension and a short suggestion fragment."""
    base = f"{question_type} 面试题 {' '.join(filter(None, [position, difficulty]))}".strip()

    extras: list[str] = []
    if hints.focus_dimensions:
        extras.append(hints.focus_dimensions[0])
    if hints.active_suggestion:
        extras.append(hints.active_suggestion[:_MAX_SUGGESTION_QUERY_LEN])

    if extras:
        return f"{base} {' '.join(extras)}".strip()
    return base


def filter_and_rerank(
    *,
    sources: list[dict[str, Any]],
    hints: PickerHints,
    manifest_index: dict[str, dict[str, Any]],
    requested_difficulty: str,
) -> list[dict[str, Any]]:
    """Stable re-rank of RAG sources using profile hints + manifest tags.

    - Bonus when source's question_type is in focus_question_types.
    - Bonus when source's difficulty matches the (possibly adjusted) request.
    - Soft penalty when the source's question_type is in avoid_question_types.
    - Original retrieval order acts as a tie-breaker so we never flip cleanly
      ranked results into noise; if the post-filter list is empty, fall back
      to the original sources unchanged.
    """
    if not sources:
        return sources

    target_difficulty = (
        hints.suggested_difficulty or requested_difficulty or ""
    ).strip().lower()

    enriched: list[tuple[float, int, dict[str, Any]]] = []
    for idx, src in enumerate(sources):
        if not isinstance(src, dict):
            continue
        file_name = str(src.get("title") or src.get("file_name") or "")
        meta = manifest_index.get(file_name, {})
        src_qt = str(
            meta.get("estimated_question_type")
            or src.get("question_type")
            or ""
        ).strip()
        src_diff = str(
            meta.get("estimated_difficulty")
            or src.get("difficulty")
            or ""
        ).strip().lower()

        try:
            base_score = float(src.get("score") or 0.0)
        except (TypeError, ValueError):
            base_score = 0.0

        bonus = 0.0
        if src_qt and src_qt in hints.focus_question_types:
            bonus += 0.15
        if target_difficulty and src_diff == target_difficulty:
            bonus += 0.10
        if src_qt and src_qt in hints.avoid_question_types:
            bonus -= 0.20

        enriched.append((base_score + bonus, idx, src))

    if not enriched:
        return sources

    # Sort by adjusted score desc, then by original idx asc (stable tie-break).
    enriched.sort(key=lambda item: (-item[0], item[1]))
    reranked = [src for _, _, src in enriched]
    return reranked or list(sources)


__all__ = [
    "PickerHints",
    "resolve_picker_hints",
    "build_query_with_hints",
    "filter_and_rerank",
]
