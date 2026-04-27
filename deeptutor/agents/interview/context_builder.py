"""Pre-interview context assembly — prepares role-specific memory context
before a mock interview session starts.

Different agents get different views of the learner's history:
- AI Examinee: user skill level, answer style reference
- Interviewer: scoring rules, historical weak points, followup strategy
- Scoring Agent: full current session answers, rubric dimensions
- Review Agent: current session + historical trends
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.interview import InterviewMemoryService, LearnerProfile

from .models import InterviewSession


def build_interviewer_context(
    *,
    profile: LearnerProfile,
    recent_sessions: list[InterviewSession],
    question_type: str = "",
) -> str:
    """Build context for the interview examiner agent."""
    parts = ["## 考生画像摘要"]

    stable = profile.stable
    if stable.target_exam_type:
        parts.append(f"- 目标考试：{stable.target_exam_type}")
    if stable.target_position:
        parts.append(f"- 目标岗位：{stable.target_position}")
    if stable.current_stage:
        parts.append(f"- 备考阶段：{stable.current_stage}")

    dynamic = profile.dynamic
    if dynamic.recent_weak_types:
        parts.append(f"- 近期薄弱题型：{'、'.join(dynamic.recent_weak_types)}")
    if dynamic.recent_low_score_dimensions:
        weak_dims = [
            d.get("dimension", "")
            for d in dynamic.recent_low_score_dimensions
            if d.get("score", 10) <= 5
        ]
        if weak_dims:
            parts.append(f"- 近期低分维度：{'、'.join(weak_dims[:3])}")

    if recent_sessions:
        parts.append(f"\n最近{len(recent_sessions)}场同题型训练摘要：")
        for s in recent_sessions[-3:]:
            parts.append(
                f"- {s.question_type}: {s.total_score}/80"
                + (f" — {s.training_suggestion[:60]}" if s.training_suggestion else "")
            )

    return "\n".join(parts)


def build_examinee_context(
    *,
    profile: LearnerProfile,
    recent_sessions: list[InterviewSession],
) -> str:
    """Build context for the AI examinee (for simulated answers)."""
    parts = ["## AI考生参考信息"]

    stable = profile.stable
    if stable.target_exam_type:
        parts.append(f"- 目标考试：{stable.target_exam_type}")
    if stable.target_position:
        parts.append(f"- 目标岗位：{stable.target_position}")

    if stable.needs_template_prompt:
        parts.append("- 该考生偏好使用答题模板，AI考生应展示有结构的回答")
    if stable.needs_high_score_demo:
        parts.append("- 该考生需要高分示范参考")

    parts.append(f"\n当前水平参考：")

    if recent_sessions:
        avg = sum(s.total_score for s in recent_sessions) / len(recent_sessions)
        if avg >= 60:
            parts.append("- 该考生表现优秀，AI考生应模拟高质量作答水平")
        elif avg >= 40:
            parts.append("- 该考生表现中等，AI考生应模拟有改进空间的作答")
        else:
            parts.append("- 该考生处于基础阶段，AI考生应模拟有常见问题的作答")

    return "\n".join(parts)


def build_scoring_context(
    *,
    question: str,
    answer: str,
    followup_question: str = "",
    followup_answer: str = "",
    profile: LearnerProfile | None = None,
) -> str:
    """Build context for the scoring agent — primarily the session data itself."""
    parts = [f"## 本场面试评分\n题目：{question}", f"考生作答：{answer}"]

    if followup_question:
        parts.append(f"追问：{followup_question}")
    if followup_answer:
        parts.append(f"追问作答：{followup_answer}")

    if profile:
        dynamic = profile.dynamic
        if dynamic.recent_deduction_reasons:
            parts.append(f"历史常见扣分：{'；'.join(dynamic.recent_deduction_reasons[:3])}")

    return "\n\n".join(parts)


def build_review_context(
    *,
    session: InterviewSession,
    previous_sessions: list[InterviewSession],
    profile: LearnerProfile | None = None,
) -> str:
    """Build context for the review agent."""
    parts = ["## 复盘上下文"]

    parts.append(
        f"本场：{session.question_type} | 题目：{session.question_text[:100]}..."
    )
    parts.append(f"评分：{session.total_score}/80")

    if previous_sessions:
        parts.append(f"\n历史同题型训练：{len(previous_sessions)}场")
        for prev in previous_sessions[-3:]:
            parts.append(
                f"- {prev.completed_at or '未知'}: {prev.total_score}/80"
            )

    if profile:
        dynamic = profile.dynamic
        if dynamic.recent_trend:
            parts.append(f"总体趋势：{dynamic.recent_trend}")

    return "\n".join(parts)
