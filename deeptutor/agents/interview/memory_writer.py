"""Post-interview memory writer — extracts facts from a completed session
and persists them to the user's InterviewMemoryService.

Write discipline (aligned with the design doc):
- Only writes at: session end, review generated
- Never writes: single-turn chatter, transient observations
- Every conclusion must have a source (which session/score)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from deeptutor.logging import Logger, get_logger
from deeptutor.services.interview import (
    DynamicProfile,
    InterviewMemoryService,
    LearnerProfile,
    StableProfile,
)

from .models import DimensionScore, InterviewSession

logger: Logger = get_logger("MemoryWriter")


async def write_session_to_memory(
    *,
    session: InterviewSession,
    memory_service: InterviewMemoryService,
) -> None:
    """Write a completed interview session and update the learner profile.

    This is the central write function — call it once after the review is done.
    """
    if not session.session_id:
        logger.warning("Cannot write session without session_id")
        return

    # 1. Save the full session record
    memory_service.save_session(session)

    # 2. Update the learner profile
    profile = memory_service.read_profile()
    recent_sessions = [session, *memory_service.get_recent_sessions(limit=9)]
    _update_profile_from_sessions(profile, recent_sessions, latest_session=session)
    memory_service.save_profile(profile)

    logger.info(
        f"Wrote session {session.session_id} for user {session.user_id} "
        f"(total_score={session.total_score:.1f})"
    )


def _update_profile_from_session(
    profile: LearnerProfile,
    session: InterviewSession,
) -> None:
    _update_profile_from_sessions(profile, [session], latest_session=session)


def _update_profile_from_sessions(
    profile: LearnerProfile,
    sessions: list[InterviewSession],
    *,
    latest_session: InterviewSession,
) -> None:
    """Extract long-term facts from a session and merge into the profile.

    Only high-confidence, repeated patterns get promoted to the stable profile.
    Dynamic profile gets updated with the latest session observations.
    """
    now = datetime.now().astimezone().isoformat()
    sessions = _unique_sessions(sessions)

    # ── Update stable profile (only when explicitly set) ──────────
    if latest_session.exam_type and not profile.stable.target_exam_type:
        profile.stable.target_exam_type = latest_session.exam_type
    if latest_session.position and not profile.stable.target_position:
        profile.stable.target_position = latest_session.position
    profile.stable.updated_at = now

    # ── Update dynamic profile ────────────────────────────────────
    dynamic = profile.dynamic
    dynamic.updated_at = now

    # Extract weak dimensions (score ≤ 5.0)
    low_scores = _recent_low_score_dimensions(sessions, now=now)
    dynamic.recent_low_score_dimensions = low_scores[:8]
    repeated, resolved = _repeated_and_resolved_dimensions(sessions)
    dynamic.repeated_weak_dimensions = repeated[:5]
    dynamic.resolved_dimensions = resolved[:5]
    dynamic.dimension_trends = _dimension_trends(sessions)[:8]

    # Extract deduction reasons
    dynamic.recent_deduction_reasons = _recent_deduction_reasons(sessions)[:8]

    followup_issues = [_build_followup_issue(item) for item in sessions if item.followup_question]
    dynamic.recent_followup_issues = _unique_keep_order(followup_issues)[:5]

    dynamic.recent_weak_types = _weak_question_types(sessions)[:5]

    suggestion_history = _training_suggestion_history(sessions)[:8]
    dynamic.training_suggestion_history = suggestion_history
    if latest_session.training_suggestion:
        dynamic.current_training_suggestion = latest_session.training_suggestion
    elif suggestion_history:
        dynamic.current_training_suggestion = str(suggestion_history[0].get("suggestion") or "")

    dynamic.recent_trend = _overall_trend(sessions, low_scores=low_scores)


def _unique_sessions(sessions: list[InterviewSession]) -> list[InterviewSession]:
    result: list[InterviewSession] = []
    seen: set[str] = set()
    for session in sessions:
        key = session.session_id or f"{session.completed_at}:{session.question_text[:30]}"
        if key in seen:
            continue
        seen.add(key)
        result.append(session)
    return sorted(
        result,
        key=lambda item: item.completed_at or item.started_at or "",
        reverse=True,
    )


def _recent_low_score_dimensions(
    sessions: list[InterviewSession],
    *,
    now: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for session in sessions:
        for score in session.scores:
            if score.score <= 5.0:
                items.append(
                    {
                        "dimension": score.dimension,
                        "score": score.score,
                        "max_score": score.max_score,
                        "session_id": session.session_id,
                        "question_type": session.question_type,
                        "completed_at": session.completed_at,
                        "deduction_reason": score.deduction_reason,
                        "updated_at": now,
                    }
                )
    return items


def _repeated_weak_dimensions(sessions: list[InterviewSession]) -> list[dict[str, Any]]:
    """Back-compat wrapper returning only the still-active repeated weaknesses."""
    repeated, _ = _repeated_and_resolved_dimensions(sessions)
    return repeated


def _repeated_and_resolved_dimensions(
    sessions: list[InterviewSession],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split historically-low dimensions into still-weak vs recovered.

    A dimension is "resolved" when it has ≥2 historical lows but its latest
    score is ≥6 AND the most recent session did not flag it as low. This
    lets `recent_weak_dimensions` reflect the current training state instead
    of cumulative history.
    """
    chronological = sorted(
        sessions,
        key=lambda item: item.completed_at or item.started_at or "",
    )
    by_dimension: dict[str, list[tuple[InterviewSession, DimensionScore]]] = defaultdict(list)
    for session in chronological:
        for score in session.scores:
            if score.dimension:
                by_dimension[score.dimension].append((session, score))

    repeated: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    for dimension, pairs in by_dimension.items():
        lows = [pair for pair in pairs if pair[1].score <= 5.0]
        if len(lows) < 2:
            continue
        latest_session, latest_score = pairs[-1]
        entry = {
            "dimension": dimension,
            "count": len(lows),
            "latest_score": latest_score.score,
            "latest_session_id": latest_session.session_id,
            "question_types": _unique_keep_order(
                session.question_type for session, _ in lows if session.question_type
            ),
            "deduction_reasons": _unique_keep_order(
                score.deduction_reason for _, score in lows if score.deduction_reason
            )[:3],
        }
        if latest_score.score >= 6.0:
            entry["resolved_at"] = latest_session.completed_at or latest_session.started_at or ""
            resolved.append(entry)
        else:
            repeated.append(entry)

    repeated.sort(key=lambda item: (item["count"], -float(item["latest_score"])), reverse=True)
    resolved.sort(key=lambda item: (item["count"], float(item["latest_score"])), reverse=True)
    return repeated, resolved


def _dimension_trends(sessions: list[InterviewSession]) -> list[dict[str, Any]]:
    chronological = sorted(
        sessions,
        key=lambda item: item.completed_at or item.started_at or "",
    )
    by_dimension: dict[str, list[tuple[InterviewSession, DimensionScore]]] = defaultdict(list)
    for session in chronological:
        for score in session.scores:
            if score.dimension:
                by_dimension[score.dimension].append((session, score))

    trends: list[dict[str, Any]] = []
    for dimension, pairs in by_dimension.items():
        first_session, first_score = pairs[0]
        latest_session, latest_score = pairs[-1]
        delta = round(latest_score.score - first_score.score, 1)
        if len(pairs) < 2:
            status = "insufficient_data"
        elif latest_score.score <= 5.0 and sum(1 for _, score in pairs if score.score <= 5.0) >= 2:
            status = "persistently_weak"
        elif delta >= 1.0:
            status = "improving"
        elif delta <= -1.0:
            status = "declining"
        else:
            status = "stable"
        trends.append(
            {
                "dimension": dimension,
                "first_score": first_score.score,
                "latest_score": latest_score.score,
                "delta": delta,
                "sessions": len(pairs),
                "status": status,
                "first_session_id": first_session.session_id,
                "latest_session_id": latest_session.session_id,
            }
        )
    priority = {
        "declining": 4,
        "persistently_weak": 3,
        "improving": 2,
        "stable": 1,
        "insufficient_data": 0,
    }
    trends.sort(key=lambda item: (priority.get(str(item["status"]), 0), item["sessions"]), reverse=True)
    return trends


def _recent_deduction_reasons(sessions: list[InterviewSession]) -> list[str]:
    reasons: list[str] = []
    for session in sessions:
        for score in session.scores:
            if score.deduction_reason:
                reasons.append(score.deduction_reason)
    return _unique_keep_order(reasons)


def _weak_question_types(sessions: list[InterviewSession]) -> list[str]:
    counts: Counter[str] = Counter()
    latest_order: dict[str, int] = {}
    for idx, session in enumerate(sessions):
        if not session.question_type:
            continue
        low_dimension = any(score.score <= 5.0 for score in session.scores)
        if session.total_score < 40 or low_dimension:
            counts[session.question_type] += 1
            latest_order.setdefault(session.question_type, idx)
    return [
        item
        for item, _ in sorted(
            counts.items(),
            key=lambda pair: (pair[1], -latest_order.get(pair[0], 0)),
            reverse=True,
        )
    ]


def _training_suggestion_history(sessions: list[InterviewSession]) -> list[dict[str, Any]]:
    """Build deduplicated suggestion history with active/expired status.

    `sessions` arrives newest-first (see `_unique_sessions`). The newest
    suggestion is `active`; everything older with a distinct text is `expired`.
    """
    history: list[dict[str, Any]] = []
    seen: set[str] = set()
    for session in sessions:
        suggestion = session.training_suggestion.strip()
        if not suggestion or suggestion in seen:
            continue
        seen.add(suggestion)
        history.append(
            {
                "session_id": session.session_id,
                "question_type": session.question_type,
                "completed_at": session.completed_at,
                "suggestion": suggestion,
                "status": "active" if not history else "expired",
            }
        )
    return history


def _overall_trend(
    sessions: list[InterviewSession],
    *,
    low_scores: list[dict[str, Any]],
) -> str:
    scored = [session for session in sessions if session.total_score > 0]
    if len(scored) >= 2:
        chronological = sorted(scored, key=lambda item: item.completed_at or item.started_at or "")
        delta = chronological[-1].total_score - chronological[0].total_score
        if delta >= 8:
            return f"最近{len(scored)}场总分上升，继续巩固高频弱项"
        if delta <= -8:
            return f"最近{len(scored)}场总分下降，需复盘答题结构和素材质量"

    repeated = _repeated_weak_dimensions(sessions)
    if repeated:
        names = "、".join(str(item.get("dimension")) for item in repeated[:2])
        return f"反复薄弱维度：{names}"
    if low_scores:
        return "需重点关注最近低分维度"
    return "表现稳定"


def _unique_keep_order(items: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _build_followup_issue(session: InterviewSession) -> str:
    if session.followup_answer:
        return f"{session.question_type or '通用题型'}追问已完成：{session.followup_question[:80]}"
    return f"{session.question_type or '通用题型'}追问未作答：{session.followup_question[:80]}"
