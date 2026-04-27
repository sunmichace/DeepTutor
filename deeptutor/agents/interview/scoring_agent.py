"""Interview scoring agent — evaluates answer against rubric dimensions."""

from __future__ import annotations

import json
from typing import Any

from deeptutor.logging import Logger, get_logger
from deeptutor.services.llm import stream as llm_stream

from .models import DimensionScore

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

logger: Logger = get_logger("ScoringAgent")


async def score_answer(
    *,
    question: str,
    answer: str,
    followup_question: str = "",
    followup_answer: str = "",
    question_type: str = "",
    position: str = "",
    language: str = "zh",
    temperature: float = 0.2,
) -> tuple[list[DimensionScore], float]:
    """Score a candidate's answer against the rubric dimensions.

    Returns (dimension_scores, total_score).
    """
    system_prompt = _build_scoring_system_prompt(language)
    user_prompt = _build_scoring_user_prompt(
        question=question,
        answer=answer,
        followup_question=followup_question,
        followup_answer=followup_answer,
        question_type=question_type,
        position=position,
    )

    chunks: list[str] = []
    async for c in llm_stream(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=1500,
    ):
        chunks.append(c)

    raw = "".join(chunks).strip()
    scores, total = _parse_scores(raw)

    if not scores:
        logger.warning("Scoring returned no dimensions; using zeros.")
        scores = [DimensionScore(dimension=d, score=0.0, max_score=10.0) for d in _RUBRIC_DIMENSIONS]
        total = 0.0

    return scores, total


def _build_scoring_system_prompt(language: str) -> str:
    if language.startswith("zh"):
        return (
            "你是一位公考/事业编面试评分专家。请严格根据评分维度对考生的作答进行评分。\n\n"
            "评分维度（每项满分10分）：\n"
            "1. 审题与立意：是否准确理解题目要求，立意是否得当。\n"
            "2. 结构化表达：回答是否有清晰的结构（开头-主体-结尾）。\n"
            "3. 逻辑完整性：论点之间的逻辑关系是否严密。\n"
            "4. 论据与案例质量：使用的论据和案例是否贴切、有说服力。\n"
            "5. 岗位匹配度：回答是否体现对岗位的理解和匹配意识。\n"
            "6. 语言自然度：表达是否自然流畅，避免背稿感。\n"
            "7. 临场应对：面对压力或追问时的稳定性。\n"
            "8. 追问应答质量：对追问的理解和回应质量。\n\n"
            "评分规则：\n"
            "- 8-10分：优秀，无明显不足\n"
            "- 6-7分：良好，有少量扣分点\n"
            "- 4-5分：一般，存在明显问题\n"
            "- 2-3分：较差，多个维度需要大幅提升\n"
            "- 0-1分：极差，基本未作答或完全跑题\n\n"
            "请以JSON格式输出评分结果，格式如下：\n"
            '{"scores": [{"dimension": "审题与立意", "score": 7, "max_score": 10, "deduction_reason": "扣分原因", "evidence": "扣分证据（引用考生原话）"}], "total_score": 56}\n\n'
            "只输出JSON，不要包含其他文字。"
        )
    return "You are an interview scoring expert. Score answers against rubric dimensions (max 10 each). Output JSON only."


def _build_scoring_user_prompt(
    *,
    question: str,
    answer: str,
    followup_question: str,
    followup_answer: str,
    question_type: str,
    position: str,
) -> str:
    parts = [f"题目：{question}", f"考生作答：{answer}"]

    if followup_question:
        parts.append(f"追问问题：{followup_question}")
    if followup_answer:
        parts.append(f"考生追问作答：{followup_answer}")

    if question_type:
        parts.append(f"题型：{question_type}")
    if position:
        parts.append(f"岗位方向：{position}")

    parts.append("\n请基于以上信息输出评分JSON：")

    return "\n\n".join(parts)


def _parse_scores(raw: str) -> tuple[list[DimensionScore], float]:
    """Parse LLM output into DimensionScore list."""
    import re

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return [], 0.0
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return [], 0.0

    raw_scores = data.get("scores", [])
    if not raw_scores:
        return [], 0.0

    scores = [
        DimensionScore(
            dimension=s.get("dimension", f"维度{i+1}"),
            score=float(s.get("score", 0)),
            max_score=float(s.get("max_score", 10)),
            deduction_reason=s.get("deduction_reason", ""),
            evidence=s.get("evidence", ""),
        )
        for i, s in enumerate(raw_scores)
    ]

    total = float(data.get("total_score", 0))
    if total <= 0 and scores:
        total = sum(s.score for s in scores)

    return scores, total
