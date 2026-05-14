"""Interview review agent — generates structured post-interview review reports."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from deeptutor.logging import Logger, get_logger
from deeptutor.services.llm import complete as llm_complete

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


class TrainingSuggestionPayload(BaseModel):
    """Structured training suggestion extracted from the review report."""

    focus_dimension: str = Field(default="", max_length=40)
    suggestion: str = Field(default="", max_length=200)
    drills: list[str] = Field(default_factory=list, max_length=5)

    def to_text(self) -> str:
        text = (self.suggestion or "").strip()
        if not text:
            return ""
        drills = [d.strip() for d in self.drills if d and d.strip()][:3]
        if drills:
            text = f"{text}（{'；'.join(drills)}）"
        if self.focus_dimension:
            focus = self.focus_dimension.strip()
            if focus and focus not in text:
                text = f"[{focus}] {text}"
        return text[:200]


_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)


def extract_training_suggestion_payload(review_text: str) -> TrainingSuggestionPayload | None:
    """Return a validated payload if the LLM emitted a JSON block, else None."""
    match = _JSON_BLOCK_RE.search(review_text or "")
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(f"training suggestion JSON parse failed: {exc}")
        return None
    if not isinstance(data, dict):
        return None
    try:
        return TrainingSuggestionPayload.model_validate(data)
    except ValidationError as exc:
        logger.warning(f"training suggestion schema invalid: {exc}")
        return None


async def generate_review(
    *,
    session: InterviewSession,
    previous_sessions: list[InterviewSession] | None = None,
    language: str = "zh",
) -> str:
    """Generate a structured review report for a completed interview session."""
    system_prompt = _build_review_system_prompt(language)
    user_prompt = _build_review_user_prompt(session, previous_sessions or [])

    raw = (await llm_complete(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=2000,
    )).strip()
    return clamp_review_length(raw)


_REVIEW_HARD_CAP = 2400


def clamp_review_length(review_text: str, *, hard_cap: int = _REVIEW_HARD_CAP) -> str:
    """Trim oversize review text while preserving the most actionable parts.

    Priorities, in order, when the total length exceeds ``hard_cap``:
      1. Opening summary (first paragraph or "本次表现总结" section).
      2. "下一步训练建议" section.
      3. The trailing ```json``` block (so structured extraction keeps working).
      4. As much of the middle body as the remaining budget allows.

    If the input fits the cap, it is returned untouched.
    """
    text = (review_text or "").strip()
    if not text or len(text) <= hard_cap:
        return text

    # Reserve ~25% each for opening and suggestion, the rest is middle/json budget.
    opening_budget = max(hard_cap // 4, 200)
    suggestion_budget = max(hard_cap // 4, 200)

    json_match = _JSON_BLOCK_RE.search(text)
    json_block = json_match.group(0).strip() if json_match else ""
    body = (text[: json_match.start()] if json_match else text).strip()

    opening = _slice_section(body, "本次表现总结") or _slice_first_paragraph(body)
    opening = opening[:opening_budget].rstrip()

    suggestion = _slice_section(body, "下一步训练建议")
    suggestion = suggestion[:suggestion_budget].rstrip()

    # Glue separators (\n\n between non-empty segments) cost ~2 chars each.
    separator_overhead = 6
    middle_budget = (
        hard_cap - len(opening) - len(suggestion) - len(json_block) - separator_overhead
    )
    middle_budget = max(middle_budget, 0)
    middle = _slice_middle(body, opening=opening, suggestion=suggestion)
    middle = middle[:middle_budget].rstrip()

    sections = [seg for seg in (opening, middle, suggestion, json_block) if seg]
    out = "\n\n".join(sections)
    # Final guard: if section-level trims still exceed the cap (very short caps,
    # heavy CJK escapes, etc.), apply a hard truncation.
    if len(out) > hard_cap:
        out = out[:hard_cap].rstrip()
    return out


def _slice_section(body: str, heading: str) -> str:
    """Return the lines under ``heading`` until the next 1-N. heading or end."""
    lines = body.splitlines()
    start = -1
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if heading in line and (
            line.startswith(heading)
            or re.match(rf"^[0-9一二三四五六七八九]+[.、:：]\s*{re.escape(heading)}", line)
            or line.startswith(f"## {heading}")
        ):
            start = idx
            break
    if start < 0:
        return ""
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        line = lines[idx].strip()
        if not line:
            continue
        if any(other != heading and other in line for other in _REVIEW_SECTIONS):
            end = idx
            break
        if line.startswith("```"):
            end = idx
            break
    return "\n".join(lines[start:end]).strip()


def _slice_first_paragraph(body: str) -> str:
    for para in body.split("\n\n"):
        text = para.strip()
        if text:
            return text
    return ""


def _slice_middle(body: str, *, opening: str, suggestion: str) -> str:
    middle = body
    if opening:
        middle = middle.replace(opening, "", 1)
    if suggestion:
        middle = middle.replace(suggestion, "", 1)
    return middle.strip()


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
            "报告正文之后，必须再额外输出一个独立的 ```json ... ``` 代码块，"
            "内容是一个对象，字段如下：\n"
            "- focus_dimension: 本次最应优先训练的评分维度名，字符串，≤40字。\n"
            "- suggestion: 一句具体、可执行的训练建议，字符串，≤200字。\n"
            "- drills: 1-3 条具体训练动作的字符串数组。\n\n"
            "要求：\n"
            "- 语言简洁、具体、可操作\n"
            "- 每个结论都要有评分证据支撑\n"
            "- 改进建议要具体，不要泛泛而谈\n"
            "- 保持鼓励和支持的语气\n"
            "- JSON 代码块必须是合法 JSON，放在报告最后"
        )
    return (
        "You are an interview review teacher. Generate a structured review report. "
        "Include: summary, dimension analysis, key deductions, followup assessment, "
        "historical comparison, and training recommendations. "
        "After the narrative, emit a fenced ```json``` block with keys "
        "focus_dimension (str ≤40 chars), suggestion (str ≤200 chars) "
        "and drills (1-3 short strings)."
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
