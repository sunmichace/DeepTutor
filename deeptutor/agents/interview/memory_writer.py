"""Post-interview memory writer — extracts facts from a completed session
and persists them to the user's InterviewMemoryService.

Write discipline (aligned with the design doc):
- Only writes at: session end, review generated
- Never writes: single-turn chatter, transient observations
- Every conclusion must have a source (which session/score)
"""

from __future__ import annotations

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
    _update_profile_from_session(profile, session)
    memory_service.save_profile(profile)

    logger.info(
        "Wrote session %s for user %s (total_score=%.1f)",
        session.session_id,
        session.user_id,
        session.total_score,
    )


def _update_profile_from_session(
    profile: LearnerProfile,
    session: InterviewSession,
) -> None:
    """Extract long-term facts from a session and merge into the profile.

    Only high-confidence, repeated patterns get promoted to the stable profile.
    Dynamic profile gets updated with the latest session observations.
    """
    now = datetime.now().astimezone().isoformat()

    # ── Update stable profile (only when explicitly set) ──────────
    if session.exam_type and not profile.stable.target_exam_type:
        profile.stable.target_exam_type = session.exam_type
    if session.position and not profile.stable.target_position:
        profile.stable.target_position = session.position
    profile.stable.updated_at = now

    # ── Update dynamic profile ────────────────────────────────────
    dynamic = profile.dynamic
    dynamic.updated_at = now

    # Extract weak dimensions (score ≤ 5.0)
    low_scores = [
        {"dimension": s.dimension, "score": s.score, "max_score": s.max_score}
        for s in session.scores
        if s.score <= 5.0
    ]
    if low_scores:
        existing = [d for d in dynamic.recent_low_score_dimensions if d.get("dimension") != low_scores[0].get("dimension")]
        dynamic.recent_low_score_dimensions = (low_scores + existing)[:5]

    # Extract deduction reasons
    reasons = [s.deduction_reason for s in session.scores if s.deduction_reason]
    if reasons:
        dynamic.recent_deduction_reasons = (reasons + dynamic.recent_deduction_reasons)[:5]

    # Track question type as weak if score is low
    if session.question_type and session.total_score < 40:
        existing = [t for t in dynamic.recent_weak_types if t != session.question_type]
        dynamic.recent_weak_types = [session.question_type] + existing
        dynamic.recent_weak_types = dynamic.recent_weak_types[:5]

    # Training suggestion from the review report (first line if available)
    if session.training_suggestion:
        dynamic.current_training_suggestion = session.training_suggestion

    # Trend estimate — placeholder for now, will be enhanced in P1
    if low_scores:
        dynamic.recent_trend = "需重点关注低分维度"
    else:
        dynamic.recent_trend = "表现稳定"
