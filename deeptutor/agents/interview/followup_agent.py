"""Follow-up question agent — decides whether to follow up and generates the question."""

from __future__ import annotations

from deeptutor.logging import Logger, get_logger
from deeptutor.services.llm import stream as llm_stream

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

    chunks: list[str] = []
    async for c in llm_stream(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.1,
        max_tokens=50,
    ):
        chunks.append(c)

    raw = "".join(chunks).strip().upper()
    return raw.startswith("YES") or raw.startswith("是")


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
        "你是一位公考面试考官。请根据考生的回答生成一个有针对性的追问。\n\n"
        "追问要求：\n"
        "- 针对回答中的薄弱环节（论据不足、逻辑跳跃、立意偏浅）\n"
        "- 追问要具体，不要泛泛而问\n"
        "- 追问难度适当，不宜过于刁钻\n"
        "- 追问应给考生补全和深入的机会\n"
        "- 追问长度控制在50字以内"
    ) if language.startswith("zh") else (
        "Generate a targeted follow-up question based on the answer's gaps."
    )

    parts = [f"Original question: {question}", f"Candidate answer: {answer}"]
    if weak_points:
        parts.append(f"Known weak areas: {', '.join(weak_points)}")
    if question_type:
        parts.append(f"Question type: {question_type}")
    if position:
        parts.append(f"Position: {position}")
    parts.append("\nFollow-up question:")

    user_prompt = "\n\n".join(parts)

    chunks: list[str] = []
    async for c in llm_stream(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=200,
    ):
        chunks.append(c)

    return "".join(chunks).strip()
