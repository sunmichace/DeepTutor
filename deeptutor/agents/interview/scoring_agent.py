"""Interview scoring agent — evaluates answer against rubric dimensions."""

from __future__ import annotations

import json
from typing import Any

from deeptutor.logging import Logger, get_logger
from deeptutor.services.llm import complete as llm_complete

from .models import DimensionScore

_SCORING_MAX_ATTEMPTS = 2

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

    scores: list[DimensionScore] = []
    total = 0.0
    raw = ""
    for attempt in range(_SCORING_MAX_ATTEMPTS):
        try:
            raw = (
                await llm_complete(
                    prompt=_build_retry_user_prompt(user_prompt, attempt=attempt),
                    system_prompt=system_prompt,
                    temperature=temperature if attempt == 0 else 0.0,
                    max_tokens=4000,
                    max_retries=1,
                    retry_delay=2.0,
                    response_format={"type": "json_object"},
                )
            ).strip()
        except Exception as exc:
            logger.warning(f"Scoring LLM call failed; using heuristic fallback. error={exc}")
            break
        scores, total = _parse_scores(raw)
        if scores:
            break
        logger.warning(
            f"Scoring JSON parse failed on attempt {attempt + 1}/"
            f"{_SCORING_MAX_ATTEMPTS}; raw_len={len(raw)}"
        )

    if not scores:
        logger.warning("Scoring returned no parseable dimensions; using heuristic fallback.")
        scores, total = _heuristic_scores(
            question=question,
            answer=answer,
            followup_question=followup_question,
            followup_answer=followup_answer,
        )

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


def _build_retry_user_prompt(user_prompt: str, *, attempt: int) -> str:
    if attempt == 0:
        return user_prompt
    return (
        f"{user_prompt}\n\n"
        "上一次输出无法解析。请重新输出严格 JSON 对象，必须包含 scores 数组和 total_score 数字；"
        "不要输出解释、Markdown、思考过程或多余文本。"
    )


def _parse_scores(raw: str) -> tuple[list[DimensionScore], float]:
    """Parse LLM output into DimensionScore list."""
    import re

    def _try_parse(text: str) -> dict | None:
        """Try to parse JSON, attempting to fix truncated output."""
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        fixed = _balance_json_text(text)
        if fixed != text:
            try:
                parsed = json.loads(fixed)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                pass
        return None

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()
    cleaned = cleaned.strip("` \n\t")

    # Try parsing the whole output as JSON
    data = _try_parse(cleaned)
    if data is not None and data.get("scores"):
        scores = _build_scores(data)
        if scores:
            return scores, _calc_total(data, scores)

    # Some models (DeepSeek) output reasoning before the JSON.
    # Find the LAST JSON object in the text, preferring one with "scores" key.
    # Strategy: find all brace-delimited substrings and try each.
    candidates: list[str] = []
    depth = 0
    start = -1
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(cleaned[start:i+1])
                start = -1

    # Try candidates from last to first (prefer later output)
    for candidate in reversed(candidates):
        data = _try_parse(candidate)
        if data is not None and data.get("scores"):
            scores = _build_scores(data)
            if scores:
                return scores, _calc_total(data, scores)

    # Fallback: try regex on the whole text (greedy, last match)
    matches = list(re.finditer(r"\{[\s\S]*?\}", cleaned))
    if matches:
        for m in reversed(matches):
            data = _try_parse(m.group())
            if data is not None and data.get("scores"):
                scores = _build_scores(data)
                if scores:
                    return scores, _calc_total(data, scores)

    logger.warning("Failed to parse scoring JSON from LLM output")
    return [], 0.0


def _balance_json_text(text: str) -> str:
    """Best-effort close of a truncated JSON object/array suffix."""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()

    if in_string:
        text += '"'
    while stack:
        opener = stack.pop()
        text += "}" if opener == "{" else "]"
    return text


def _build_scores(data: dict) -> list[DimensionScore]:
    """Build DimensionScore list from parsed data."""
    raw_scores = data.get("scores", [])
    if not raw_scores:
        return []
    parsed_scores: list[DimensionScore] = []
    for i, item in enumerate(raw_scores):
        if not isinstance(item, dict):
            continue
        score = _coerce_score(item.get("score", 0))
        max_score = _coerce_score(item.get("max_score", 10), default=10.0)
        parsed_scores.append(
            DimensionScore(
                dimension=str(item.get("dimension") or f"维度{i + 1}"),
                score=min(max(score, 0.0), max_score),
                max_score=max(max_score, 1.0),
                deduction_reason=str(item.get("deduction_reason") or ""),
                evidence=str(item.get("evidence") or ""),
            )
        )
    return _normalize_scores(parsed_scores)


def _normalize_scores(scores: list[DimensionScore]) -> list[DimensionScore]:
    """Return exactly one score for each rubric dimension."""
    if not scores:
        return []
    by_dimension: dict[str, DimensionScore] = {}
    extras: list[DimensionScore] = []
    for score in scores:
        dimension = _canonical_dimension(score.dimension)
        normalized = DimensionScore(
            dimension=dimension or score.dimension,
            score=round(min(max(score.score, 0.0), score.max_score), 1),
            max_score=max(score.max_score, 1.0),
            deduction_reason=score.deduction_reason,
            evidence=score.evidence,
        )
        if dimension and dimension not in by_dimension:
            by_dimension[dimension] = normalized
        else:
            extras.append(normalized)

    completed: list[DimensionScore] = []
    for dimension in _RUBRIC_DIMENSIONS:
        score = by_dimension.get(dimension)
        if score is None and extras:
            score = extras.pop(0)
            score.dimension = dimension
        if score is None:
            score = DimensionScore(
                dimension=dimension,
                score=6.0,
                max_score=10.0,
                deduction_reason="模型评分缺失该维度，已按保守默认分补齐。",
                evidence="模型未返回该维度评分。",
            )
        completed.append(score)
    return completed


def _canonical_dimension(value: str) -> str:
    text = str(value or "").strip()
    if text in _RUBRIC_DIMENSIONS:
        return text
    for dimension in _RUBRIC_DIMENSIONS:
        if dimension in text:
            return dimension
    return ""


def _calc_total(data: dict, scores: list[DimensionScore]) -> float:
    """Calculate total score from dimension scores.

    Some live models return ``total_score`` as an average on a 0-10 scale while
    others return the rubric sum on a 0-80 scale. Dimension scores are the
    authoritative rubric output, so summing them avoids cross-run scale drift.
    """
    if scores:
        total = sum(s.score for s in scores)
        return min(max(total, 0.0), sum(s.max_score for s in scores))
    return max(_coerce_score(data.get("total_score", 0)), 0.0)


def _coerce_score(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _heuristic_scores(
    *,
    question: str,
    answer: str,
    followup_question: str = "",
    followup_answer: str = "",
) -> tuple[list[DimensionScore], float]:
    """Deterministic non-zero fallback when live LLM output is unusable."""
    text = (answer or "").strip()
    followup_text = (followup_answer or "").strip()
    length = len(text)
    structure_hits = sum(
        1
        for marker in ("第一", "第二", "第三", "首先", "其次", "再次", "最后", "综上")
        if marker in text
    )
    case_hits = sum(1 for marker in ("例如", "比如", "案例", "我有", "结合") if marker in text)
    policy_hits = sum(1 for marker in ("政府", "制度", "保障", "规范", "培训", "群众") if marker in text)
    question_terms = [term for term in ("个人", "社会", "稳定", "发展", "岗位") if term in question]
    coverage_hits = sum(1 for term in question_terms if term in text)

    length_score = 2.0 if length < 80 else 4.0 if length < 180 else 6.0 if length < 360 else 7.0
    structure_score = min(8.0, 3.0 + structure_hits * 1.3)
    logic_score = min(8.0, 3.0 + structure_hits + coverage_hits * 0.8)
    evidence_score = min(8.0, 3.0 + case_hits * 1.2 + policy_hits * 0.4)
    position_score = min(7.0, 4.0 + policy_hits * 0.5)
    language_score = min(8.0, 4.0 + min(length, 400) / 120)
    response_score = min(8.0, max(length_score, 3.0 + structure_hits * 0.8))
    followup_score = 6.0 if not followup_question else (6.5 if followup_text else 3.0)

    values = [
        ("审题与立意", min(8.0, 3.0 + coverage_hits + (1.0 if length >= 180 else 0.0))),
        ("结构化表达", structure_score),
        ("逻辑完整性", logic_score),
        ("论据与案例质量", evidence_score),
        ("岗位匹配度", position_score),
        ("语言自然度", language_score),
        ("临场应对", response_score),
        ("追问应答质量", followup_score),
    ]
    scores = [
        DimensionScore(
            dimension=dimension,
            score=round(min(max(score, 1.0), 10.0), 1),
            max_score=10.0,
            deduction_reason="LLM评分输出不可解析，已使用本地启发式兜底评分。",
            evidence=text[:80] if text else "无有效作答文本",
        )
        for dimension, score in values
    ]
    return scores, round(sum(score.score for score in scores), 1)
