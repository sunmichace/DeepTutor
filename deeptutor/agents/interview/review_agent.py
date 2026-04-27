"""Interview review agent — generates structured post-interview review reports."""

from __future__ import annotations

from typing import Any

from deeptutor.logging import Logger, get_logger
from deeptutor.services.llm import stream as llm_stream

from .models import DimensionScore, InterviewSession

logger: Logger = get_logger("ReviewAgent")

_REVIEW_SECTIONS = [
    "本次表现总结",
    "各维度评分分析",
    "主要扣分原因",
    "追问表现评估",
    "与历史表现的对比",
    "下一步训练建议",
]


async def generate_review(
    *,
    session: InterviewSession,
    previous_sessions: list[InterviewSession] | None = None,
    language: str = "zh",
) -> str:
    """Generate a structured review report for a completed interview session."""
    system_prompt = _build_review_system_prompt(language)
    user_prompt = _build_review_user_prompt(session, previous_sessions or [])

    chunks: list[str] = []
    async for c in llm_stream(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=2000,
    ):
        chunks.append(c)

    return "".join(chunks).strip()


def _build_review_system_prompt(language: str) -> str:
    if language.startswith("zh"):
        return (
            "你是一位公考面试复盘老师。请根据考生的作答和评分生成一份结构化复盘报告。\n\n"
            "报告应包含以下部分：\n"
            "1. 本次表现总结：1-2句话概括整体表现。\n"
            "2. 各维度评分分析：列出每个评分维度的得分、扣分原因和改进建议。\n"
            "3. 主要扣分原因：总结1-3个最主要的扣分点。\n"
            "4. 追问表现评估：对追问环节的应对质量进行评价。\n"
            "5. 与历史表现的对比：如有历史数据，对比进步和退步。\n"
            "6. 下一步训练建议：给出具体的训练方向和重点。\n\n"
            "要求：\n"
            "- 语言简洁、具体、可操作\n"
            "- 每个结论都要有评分证据支撑\n"
            "- 改进建议要具体，不要泛泛而谈\n"
            "- 保持鼓励和支持的语气"
        )
    return (
        "You are an interview review teacher. Generate a structured review report. "
        "Include: summary, dimension analysis, key deductions, followup assessment, "
        "historical comparison, and training recommendations."
    )


def _build_review_user_prompt(
    session: InterviewSession,
    previous_sessions: list[InterviewSession],
) -> str:
    parts = [f"题目：{session.question_text}"]

    if session.user_answer:
        parts.append(f"考生作答：{session.user_answer[:1000]}")

    if session.followup_question:
        parts.append(f"追问问题：{session.followup_question}")
    if session.followup_answer:
        parts.append(f"追问作答：{session.followup_answer[:500]}")

    parts.append("\n评分结果：")
    for s in session.scores:
        parts.append(
            f"- {s.dimension}: {s.score}/{s.max_score}"
            + (f"（{s.deduction_reason}）" if s.deduction_reason else "")
        )
    parts.append(f"总分：{session.total_score}/{len(session.scores) * 10}")

    if previous_sessions:
        parts.append("\n历史训练记录：")
        for prev in previous_sessions[-3:]:
            parts.append(
                f"- {prev.question_type} | 总分{prev.total_score} | "
                f"完成于{prev.completed_at or '未知'}"
            )

    parts.append("\n请生成复盘报告：")
    return "\n\n".join(parts)
