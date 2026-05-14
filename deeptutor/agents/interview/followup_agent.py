"""Follow-up question agent — decides whether to follow up and generates the question."""

from __future__ import annotations

import re

from deeptutor.logging import Logger, get_logger
from deeptutor.services.llm import complete as llm_complete

logger: Logger = get_logger("FollowupAgent")


async def should_follow_up(
    *,
    question: str,
    answer: str,
    weak_points: list[str] | None = None,
    language: str = "zh",
) -> bool:
    """Decide whether a follow-up question is needed based on answer quality.

    Returns True if a follow-up would help expose a meaningful weakness.
    """
    system_prompt = (
        "你是一位公考面试考官。判断是否需要追问。\n"
        "追问条件：\n"
        "1. 考生回答明显偏题或未完整作答 → 追问\n"
        "2. 回答停留在表面，缺乏深入分析 → 追问\n"
        "3. 回答缺乏具体论据或案例 → 追问\n"
        "4. 回答结构混乱，逻辑不清 → 追问\n"
        "5. 回答完整、深入、有结构 → 不需要追问\n\n"
        "只回答 YES 或 NO。"
    ) if language.startswith("zh") else (
        "You are an interviewer. Decide if follow-up is needed. "
        "Answer YES or NO only."
    )

    parts = [f"Question: {question}", f"Answer: {answer}"]
    if weak_points:
        parts.append(f"Known weak areas: {', '.join(weak_points)}")
    user_prompt = "\n\n".join(parts)

    raw = await llm_complete(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.1,
        max_tokens=100,
    )
    return _parse_followup_decision(raw)


def _parse_followup_decision(raw: str) -> bool:
    """Parse a YES/NO-style LLM decision, tolerating brief reasoning text."""
    text = (raw or "").strip()
    if not text:
        return False

    upper = text.upper()
    tokens = re.findall(r"\bYES\b|\bNO\b", upper)
    if tokens:
        return tokens[-1] == "YES"

    if re.search(r"(不需要|无需|不用|否)", text):
        return False
    if re.search(r"(需要|应该|建议|追问|是)", text):
        return True

    first = upper.split()[0] if upper.split() else ""
    return first in {"Y", "YES"}


async def generate_followup(
    *,
    question: str,
    answer: str,
    question_type: str = "",
    position: str = "",
    weak_points: list[str] | None = None,
    language: str = "zh",
) -> str:
    """Generate a targeted follow-up question based on the answer gaps."""
    system_prompt = (
        "你是一位公考面试考官。你的任务是根据考生的回答生成一个追问。\n"
        "要求：只输出追问本身，不要输出其他任何文字。追问长度控制在50字以内。\n"
        "追问要针对回答中的薄弱环节（论据不足、逻辑跳跃、立意偏浅），要具体不泛泛。"
    ) if language.startswith("zh") else (
        "Generate a follow-up question only. Output the question itself only."
    )

    user_prompt = (
        f"题目：{question}\n"
        f"考生回答：{answer}\n"
        + (f"已知薄弱点：{'、'.join(weak_points)}\n" if weak_points else "")
        + "追问："
    )

    return (await llm_complete(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=200,
    )).strip()
