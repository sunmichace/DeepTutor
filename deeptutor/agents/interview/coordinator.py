"""MockInterviewCoordinator — orchestrates the full mock interview flow.

State machine:
  IDLE -> QUESTIONING -> ANSWERING ->
    [FOLLOWUP_QUESTION -> FOLLOWUP_ANSWERING]* ->
    SCORING -> REVIEWING -> COMPLETED

P0 constraints:
  - Max 1 followup round
  - Text-only (no audio)
  - Topics selected from the interview knowledge base (RAG)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import uuid4

from deeptutor.logging import Logger, get_logger
from deeptutor.services.interview import InterviewMemoryService, get_interview_memory_service
from deeptutor.services.rag.service import RAGService

from .context_builder import (
    build_examinee_context,
    build_interviewer_context,
    build_review_context,
    build_scoring_context,
)
from .followup_agent import generate_followup, should_follow_up
from .memory_writer import write_session_to_memory
from .models import (
    DimensionScore,
    InterviewSession,
    InterviewState,
    InterviewTurn,
)
from .picker import (
    PickerHints,
    build_query_with_hints,
    filter_and_rerank,
    resolve_picker_hints,
)
from .review_agent import extract_training_suggestion_payload, generate_review
from .scoring_agent import score_answer

logger: Logger = get_logger("MockInterviewCoordinator")

_INTERVIEW_KB = "interview_bank"

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


class MockInterviewCoordinator:
    """Orchestrate a complete mock interview session."""

    def __init__(
        self,
        user_id: str = "default",
        language: str = "zh",
        memory_service: InterviewMemoryService | None = None,
        rag_service: RAGService | None = None,
    ) -> None:
        self._user_id = user_id
        self._language = language
        self._memory = memory_service or get_interview_memory_service(user_id)
        self._rag = rag_service or RAGService()
        self._state: InterviewState = "idle"
        self._session: InterviewSession | None = None

    @property
    def state(self) -> InterviewState:
        return self._state

    @property
    def session(self) -> InterviewSession | None:
        return self._session

    def restore_session(self, session: InterviewSession) -> None:
        """Restore an in-progress session loaded from persistent memory."""
        self._session = session
        if session.completed_at:
            self._state = "completed"
        elif session.followup_question and not session.followup_answer:
            self._state = "followup_questioning"
        elif session.question_text:
            self._state = "questioning"
        else:
            self._state = "idle"

    # ── Public flow ────────────────────────────────────────────────────

    async def start_interview(
        self,
        *,
        exam_type: str = "公考面试",
        position: str = "",
        question_type: str = "综合分析",
        difficulty: str = "medium",
    ) -> dict[str, Any]:
        """Start a new mock interview: select question, build context."""
        self._state = "questioning"
        session_id = str(uuid4())

        # 1. Fetch a question from the interview knowledge base
        question_text, picker_snapshot = await self._select_question(
            question_type=question_type,
            difficulty=difficulty,
            position=position,
        )

        # 2. Read learner profile for context
        profile = self._memory.read_profile()
        recent = self._memory.get_recent_sessions(limit=5)

        # 3. Build examiner context
        examiner_context = build_interviewer_context(
            profile=profile,
            recent_sessions=recent,
            question_type=question_type,
        )

        self._session = InterviewSession(
            session_id=session_id,
            user_id=self._user_id,
            exam_type=exam_type,
            position=position,
            question_type=question_type,
            difficulty=difficulty,
            question_text=question_text,
            started_at=datetime.now().astimezone().isoformat(),
            picker_snapshot=picker_snapshot,
        )

        self._session.turns.append(
            InterviewTurn(
                role="system",
                content=examiner_context,
                turn_type="context",
            )
        )
        self._session.turns.append(
            InterviewTurn(
                role="interviewer",
                content=question_text,
                turn_type="question",
            )
        )
        self._memory.save_active_session(self._session)

        return {
            "session_id": session_id,
            "question": question_text,
            "state": self._state,
            "examiner_context": examiner_context,
        }

    async def submit_answer(self, answer: str) -> dict[str, Any]:
        """Process the examinee's answer to the main question."""
        if not self._session:
            return {"error": "No active interview session"}

        self._session.user_answer = answer
        self._session.turns.append(
            InterviewTurn(role="examinee", content=answer, turn_type="answer")
        )

        # Check if follow-up is needed
        profile = self._memory.read_profile()
        needs_followup = await should_follow_up(
            question=self._session.question_text,
            answer=answer,
            weak_points=profile.dynamic.recent_weak_types if profile else None,
            language=self._language,
        )

        if needs_followup:
            self._state = "followup_questioning"
            followup_q = await generate_followup(
                question=self._session.question_text,
                answer=answer,
                question_type=self._session.question_type,
                position=self._session.position,
                weak_points=profile.dynamic.recent_weak_types if profile else None,
                language=self._language,
            )
            self._session.followup_question = followup_q
            self._session.turns.append(
                InterviewTurn(
                    role="interviewer",
                    content=followup_q,
                    turn_type="followup",
                )
            )
            self._memory.save_active_session(self._session)
            return {
                "state": self._state,
                "followup_question": followup_q,
                "needs_followup": True,
            }

        # No followup — go straight to scoring
        return await self._score_and_review()

    async def submit_followup_answer(self, answer: str) -> dict[str, Any]:
        """Process the examinee's answer to the follow-up question."""
        if not self._session:
            return {"error": "No active interview session"}

        self._session.followup_answer = answer
        self._session.turns.append(
            InterviewTurn(
                role="examinee", content=answer, turn_type="followup_answer"
            )
        )

        return await self._score_and_review()

    async def cancel(self) -> dict[str, Any]:
        """Cancel the current interview."""
        self._state = "cancelled"
        self._memory.clear_active_session()
        return {"state": self._state, "message": "Interview cancelled"}

    # ── Internal flow ──────────────────────────────────────────────────

    async def _score_and_review(self) -> dict[str, Any]:
        """Score the session, generate review, and persist to memory."""
        if not self._session:
            return {"error": "No active interview session"}

        self._state = "scoring"

        # 1. Score the answer
        scores, total = await score_answer(
            question=self._session.question_text,
            answer=self._session.user_answer,
            followup_question=self._session.followup_question,
            followup_answer=self._session.followup_answer,
            question_type=self._session.question_type,
            position=self._session.position,
            language=self._language,
        )
        self._session.scores = scores
        self._session.total_score = total
        self._session.turns.append(
            InterviewTurn(
                role="system",
                content=json.dumps(
                    {
                        "scores": [
                            {
                                "dimension": s.dimension,
                                "score": s.score,
                                "deduction_reason": s.deduction_reason,
                            }
                            for s in scores
                        ],
                        "total_score": total,
                    },
                    ensure_ascii=False,
                ),
                turn_type="score",
            )
        )

        # 2. Generate review
        self._state = "reviewing"
        previous_sessions = self._memory.get_recent_sessions(limit=5)
        profile = self._memory.read_profile()

        review_text = await generate_review(
            session=self._session,
            previous_sessions=previous_sessions,
            language=self._language,
        )
        self._session.review_report = review_text

        # Prefer structured JSON payload; fall back to section-extraction,
        # then score-based guidance if the LLM review is truncated or malformed.
        structured = extract_training_suggestion_payload(review_text)
        structured_text = structured.to_text() if structured else ""
        self._session.training_suggestion = (
            structured_text
            or _extract_training_suggestion(review_text)
            or _build_score_based_training_suggestion(scores)
        )
        self._session.turns.append(
            InterviewTurn(
                role="system",
                content=review_text,
                turn_type="review",
            )
        )

        # 3. Mark completed
        self._state = "completed"
        self._session.completed_at = datetime.now().astimezone().isoformat()

        # 4. Persist to memory
        await write_session_to_memory(
            session=self._session,
            memory_service=self._memory,
        )
        self._memory.clear_active_session()

        return {
            "state": self._state,
            "session_id": self._session.session_id,
            "scores": [
                {
                    "dimension": s.dimension,
                    "score": s.score,
                    "max_score": s.max_score,
                    "deduction_reason": s.deduction_reason,
                    "evidence": s.evidence,
                }
                for s in scores
            ],
            "total_score": total,
            "review": review_text,
            "training_suggestion": self._session.training_suggestion,
        }

    async def _select_question(
        self,
        *,
        question_type: str,
        difficulty: str,
        position: str,
    ) -> tuple[str, dict[str, Any]]:
        """Select a question from the interview knowledge base via RAG.

        Returns a ``(question_text, picker_snapshot)`` pair. ``picker_snapshot``
        captures the hints that influenced retrieval plus the top reranked
        sources, so session persistence can later audit whether the picker
        actually steered the outcome.
        """
        profile = self._memory.read_profile()
        recent = self._memory.get_recent_sessions(limit=5)
        hints = resolve_picker_hints(
            profile=profile,
            recent_sessions=recent,
            requested_difficulty=difficulty,
        )
        effective_difficulty = hints.suggested_difficulty or difficulty
        logger.info(
            f"picker_hints kb={_INTERVIEW_KB} "
            f"req(qt={question_type or '?'},diff={difficulty or '?'},pos={position or '?'}) "
            f"eff_diff={effective_difficulty} reason={hints.reason or '-'} "
            f"focus_dim={hints.focus_dimensions} "
            f"focus_qt={hints.focus_question_types} "
            f"avoid_qt={hints.avoid_question_types}"
        )
        snapshot: dict[str, Any] = {
            "hints": hints.to_dict(),
            "requested_difficulty": difficulty,
            "effective_difficulty": effective_difficulty,
            "source_kind": "rag",
            "reranked_sources": [],
        }

        query = build_query_with_hints(
            question_type=question_type,
            difficulty=effective_difficulty,
            position=position,
            hints=hints,
        )
        snapshot["query"] = query
        try:
            result = await self._rag.search(
                query=query,
                kb_name=_INTERVIEW_KB,
            )
            if result.get("fallback"):
                _log_rag_provenance(
                    query=query,
                    question_type=question_type,
                    difficulty=effective_difficulty,
                    position=position,
                    result=result,
                )
                logger.warning(
                    "RAG returned manifest fallback for interview question selection; "
                    "using generated fallback question."
                )
                snapshot["source_kind"] = "manifest_fallback"
                return (
                    _fallback_question(
                        question_type=question_type,
                        position=position,
                    ),
                    snapshot,
                )
            sources = result.get("sources") or []
            if sources:
                reranked = filter_and_rerank(
                    sources=sources,
                    hints=hints,
                    manifest_index=_load_manifest_index(_INTERVIEW_KB),
                    requested_difficulty=effective_difficulty,
                )
                result["sources"] = reranked
                snapshot["reranked_sources"] = [
                    {
                        "title": s.get("title") or s.get("file_name") or "",
                        "score": s.get("score"),
                    }
                    for s in reranked[:5]
                    if isinstance(s, dict)
                ]
            # Log after rerank so provenance reflects the post-picker order.
            _log_rag_provenance(
                query=query,
                question_type=question_type,
                difficulty=effective_difficulty,
                position=position,
                result=result,
            )
            content = str(result.get("content", "") or result.get("answer", "") or "")
            if _is_usable_rag_content(content):
                snapshot["source_kind"] = "rag"
                return (
                    _build_question_from_rag_content(
                        content=content,
                        question_type=question_type,
                        position=position,
                        sources=result.get("sources"),
                    ),
                    snapshot,
                )
        except Exception as exc:
            logger.warning(f"RAG question selection failed, using fallback: {exc}")
            snapshot["source_kind"] = "error_fallback"
            snapshot["error"] = str(exc)[:160]
            return (
                _fallback_question(question_type=question_type, position=position),
                snapshot,
            )

        # Fallback question if RAG is unavailable
        snapshot["source_kind"] = "unusable_content_fallback"
        return (
            _fallback_question(question_type=question_type, position=position),
            snapshot,
        )


_MANIFEST_CACHE: dict[str, dict[str, dict[str, Any]]] = {}


def _load_manifest_index(kb_name: str) -> dict[str, dict[str, Any]]:
    """Load manifest files into a file_name-keyed index, cached per KB."""
    if kb_name in _MANIFEST_CACHE:
        return _MANIFEST_CACHE[kb_name]
    from pathlib import Path
    from deeptutor.services.path_service import get_path_service

    base = get_path_service().project_root / "data" / "knowledge_bases" / kb_name
    path = base / "manifest.json"
    index: dict[str, dict[str, Any]] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for entry in data.get("files", []):
                name = str(entry.get("file_name") or "")
                if name:
                    index[name] = entry
        except (json.JSONDecodeError, OSError):
            pass
    _MANIFEST_CACHE[kb_name] = index
    return index


def _log_rag_provenance(
    *,
    query: str,
    question_type: str,
    difficulty: str,
    position: str,
    result: dict[str, Any],
) -> None:
    """Emit a single-line summary of which KB files were hit and their tags.

    Intended for live CLI debugging: lets us see at a glance whether the
    selected question came from an OCR-derived source, and whether its
    tagged difficulty/question_type/position matches what was requested.
    """
    sources = result.get("sources") or []
    if not sources:
        logger.info(
            f"rag_provenance kb={_INTERVIEW_KB} "
            f"fallback={bool(result.get('fallback'))} "
            f"query={query!r} sources=0"
        )
        return

    manifest_index = _load_manifest_index(_INTERVIEW_KB)
    summaries: list[str] = []
    for src in sources[:5]:
        if not isinstance(src, dict):
            continue
        file_name = str(src.get("title") or src.get("file_name") or "")
        entry = manifest_index.get(file_name, {})
        summaries.append(
            "{name}[kind={kind},qt={qt},diff={diff},pos={pos},score={score}]".format(
                name=file_name or "?",
                kind=entry.get("source_kind") or src.get("source_kind") or "?",
                qt=entry.get("estimated_question_type") or src.get("question_type") or "?",
                diff=entry.get("estimated_difficulty") or src.get("difficulty") or "?",
                pos=entry.get("estimated_position") or src.get("position") or "?",
                score=src.get("score") or "",
            )
        )

    logger.info(
        f"rag_provenance kb={_INTERVIEW_KB} "
        f"fallback={bool(result.get('fallback'))} "
        f"req(qt={question_type or '?'},diff={difficulty or '?'},pos={position or '?'}) "
        f"hits={len(sources)} sources={' | '.join(summaries) or '<no-dict-sources>'}"
    )


def _is_usable_rag_content(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    lowered = text.lower()
    return not any(
        marker in lowered
        for marker in (
            "no documents indexed",
            "search failed:",
            "traceback ",
            "cuda error",
            "out of memory",
        )
    )


def _build_question_from_rag_content(
    *,
    content: str,
    question_type: str,
    position: str = "",
    sources: list[dict[str, Any]] | None = None,
) -> str:
    """Convert grounded RAG content into a concise interview question."""
    text = content.strip()
    if not text:
        return _fallback_question(question_type=question_type, position=position)

    question_like = _extract_question_like_sentence(text)
    if question_like:
        return question_like[:300]

    topic_hint = _extract_topic_hint(text, sources=sources)
    return _fallback_question(
        question_type=question_type,
        position=position,
        topic_hint=topic_hint,
    )


def _fallback_question(
    *,
    question_type: str,
    position: str = "",
    topic_hint: str = "",
) -> str:
    lead = (
        f"请结合{topic_hint}，谈谈你对“{question_type}”类面试题的理解。"
        if topic_hint
        else f"请谈谈你对“{question_type}”类面试题的理解。"
    )
    return (
        f"{lead}"
        f"你认为回答这类题目时最重要的是什么？"
        f"请结合你的岗位方向({position or '通用'})进行说明。"
    )


def _extract_training_suggestion(review_text: str) -> str:
    """Extract the training suggestion from a review report."""
    section_lines = _extract_section_lines(review_text, "下一步训练建议")
    if section_lines:
        suggestion = " ".join(section_lines).strip()
        if suggestion:
            return suggestion[:200]

    # Fallback: last substantive non-heading, non-table line.
    lines = [
        line.strip()
        for line in review_text.split("\n")
        if _is_substantive_suggestion_fallback_line(line)
    ]
    return lines[-1][:200] if lines else ""


def _build_score_based_training_suggestion(scores: list[DimensionScore]) -> str:
    if not scores:
        return ""
    ranked = sorted(scores, key=lambda item: item.score)
    weakest = ranked[0]
    reason = weakest.deduction_reason.strip()
    if reason:
        return f"重点训练“{weakest.dimension}”：{reason}"
    return f"重点训练“{weakest.dimension}”，补齐该维度的表达和举例。"


def _extract_question_like_sentence(text: str) -> str:
    """Return a concise question-like sentence if the source already contains one."""
    leading_text = text.split("\n\n", maxsplit=1)[0][:800]
    for raw_line in _iter_meaningful_lines(leading_text):
        line = _strip_markdown_heading(raw_line)
        if not line or line.startswith("|"):
            continue
        if any(marker in line for marker in ("？", "?", "请谈谈", "你怎么看", "如何", "为什么", "怎么", "谈谈")):
            sentence = _first_sentence(line)
            if sentence:
                return sentence
    return ""


def _extract_topic_hint(text: str, sources: list[dict[str, Any]] | None = None) -> str:
    """Derive a concise topic hint from grounded text or source metadata."""
    for raw_line in _iter_meaningful_lines(text):
        line = _strip_markdown_heading(raw_line)
        if not line or line.startswith("|"):
            continue
        sentence = _first_sentence(line)
        if sentence:
            topic = _normalize_topic_hint(sentence)
            if topic:
                return topic

    if sources:
        for source in sources:
            title = str(source.get("title", "") or source.get("file_name", "") or "").strip()
            topic = _normalize_topic_hint(title)
            if topic:
                return topic

    return ""


def _extract_section_lines(review_text: str, heading: str) -> list[str]:
    """Extract lines under a markdown-like heading until the next heading."""
    lines = review_text.splitlines()
    start_idx: int | None = None
    inline_text = ""
    for idx, raw_line in enumerate(lines):
        normalized = _normalize_heading(raw_line)
        if normalized == heading:
            start_idx = idx + 1
            break
        if normalized.startswith(f"{heading}：") or normalized.startswith(f"{heading}:"):
            inline_text = normalized[len(heading) :].lstrip("：: ").strip()
            start_idx = idx + 1
            break
        if normalized.startswith(f"{heading} "):
            inline_text = normalized[len(heading) :].strip()
            start_idx = idx + 1
            break
    if start_idx is None:
        return []

    collected: list[str] = [inline_text] if inline_text else []
    for raw_line in lines[start_idx:]:
        stripped = raw_line.strip()
        if not stripped:
            if collected:
                collected.append("")
            continue
        if _is_heading_line(stripped):
            break
        if stripped in {"---", "***"}:
            break
        collected.append(stripped)

    return [line for line in collected if line]


def _iter_meaningful_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _strip_markdown_heading(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^\d+[.、]\s*", "", line)
    line = re.sub(r"^\*\*(.*?)\*\*$", r"\1", line).strip()
    line = re.sub(r"^【[^】]*】\s*", "", line)
    return line.strip()


def _normalize_heading(line: str) -> str:
    line = _strip_markdown_heading(line)
    line = line.strip().strip("：: ")
    return line


def _is_heading_line(line: str) -> bool:
    if line.strip().startswith("#"):
        return True
    normalized = _normalize_heading(line)
    if not normalized:
        return False
    return normalized in {
        "本次表现总结",
        "各维度评分分析",
        "主要扣分原因",
        "追问表现评估",
        "与历史表现的对比",
        "下一步训练建议",
    }


def _is_substantive_suggestion_fallback_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped in {"---", "***"}:
        return False
    if stripped.startswith("|"):
        return False
    if _is_heading_line(stripped):
        return False
    normalized = _normalize_fallback_line(stripped)
    if not normalized:
        return False
    if normalized in {
        "评估结果",
        "扣分原因分析",
        "具体改进建议",
        "改进建议",
        "结束语",
    }:
        return False
    if len(normalized) < 12:
        return False
    return any(
        marker in normalized
        for marker in (
            "建议",
            "训练",
            "练习",
            "需要",
            "应该",
            "可以",
            "重点",
            "补充",
            "提升",
            "改进",
            "准备",
            "积累",
            "强化",
        )
    )


def _normalize_fallback_line(line: str) -> str:
    line = _strip_markdown_heading(line)
    line = line.strip().strip("*_` ")
    return line.strip(" ：:")


def _first_sentence(text: str) -> str:
    sentence = re.split(r"[。！？!?]", text, maxsplit=1)[0].strip()
    return sentence.strip(" ：:，,;；")


def _normalize_topic_hint(text: str) -> str:
    topic = _strip_markdown_heading(text)
    topic = _first_sentence(topic) or topic
    topic = topic.strip().strip("：:，,;；")
    if not topic:
        return ""
    if "基层治理" in topic and "法治" in topic and "自治、法治、德治" in topic:
        return "基层治理中“自治、法治、德治”"
    if "基层治理" in topic and "法治" in topic:
        return "基层治理中的法治建设"
    if len(topic) > 80:
        topic = topic[:80].rstrip("，,;；：:")
    return topic
