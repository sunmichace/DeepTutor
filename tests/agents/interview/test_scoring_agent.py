"""Unit tests for interview scoring parsing and fallback behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from deeptutor.agents.interview import scoring_agent
from deeptutor.agents.interview.scoring_agent import _parse_scores, score_answer


def test_parse_scores_repairs_truncated_json() -> None:
    raw = """
    ```json
    {"scores": [
      {"dimension": "审题与立意", "score": 6, "max_score": 10, "deduction_reason": "略浅", "evidence": "示例"}
    ], "total_score": 6
    ```
    """

    scores, total = _parse_scores(raw)

    assert len(scores) == 8
    assert scores[0].dimension == "审题与立意"
    assert total == 48


def test_parse_scores_sums_dimensions_when_total_score_is_average() -> None:
    raw = """
    {
      "scores": [
        {"dimension": "审题与立意", "score": 7, "max_score": 10},
        {"dimension": "结构化表达", "score": 8, "max_score": 10}
      ],
      "total_score": 7.5
    }
    """

    scores, total = _parse_scores(raw)

    assert len(scores) == 8
    assert total == 51


def test_parse_scores_completes_missing_rubric_dimensions() -> None:
    raw = """
    {
      "scores": [
        {"dimension": "审题与立意", "score": 8, "max_score": 10},
        {"dimension": "结构化表达", "score": 9, "max_score": 10},
        {"dimension": "逻辑完整性", "score": 8, "max_score": 10}
      ],
      "total_score": 25
    }
    """

    scores, total = _parse_scores(raw)

    assert [score.dimension for score in scores] == [
        "审题与立意",
        "结构化表达",
        "逻辑完整性",
        "论据与案例质量",
        "岗位匹配度",
        "语言自然度",
        "临场应对",
        "追问应答质量",
    ]
    assert total == 55
    assert scores[3].deduction_reason == "模型评分缺失该维度，已按保守默认分补齐。"


@pytest.mark.asyncio
async def test_score_answer_retries_unparseable_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scoring_agent,
        "llm_complete",
        AsyncMock(
            side_effect=[
                "无法解析",
                '{"scores": [{"dimension": "审题与立意", "score": 6, "max_score": 10}], "total_score": 6}',
            ]
        ),
    )

    scores, total = await score_answer(question="怎么看灵活就业？", answer="第一，要辩证看。")

    assert len(scores) == 8
    assert total == 48


@pytest.mark.asyncio
async def test_score_answer_uses_nonzero_heuristic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scoring_agent,
        "llm_complete",
        AsyncMock(return_value="完全不是 JSON"),
    )

    scores, total = await score_answer(
        question="请从个人发展和社会稳定角度谈灵活就业。",
        answer=(
            "首先，灵活就业对个人发展有积极意义。第二，它也带来保障不足的问题。"
            "第三，政府应完善制度、加强培训、规范平台用工。综上，要辩证看待。"
        ),
    )

    assert len(scores) == 8
    assert 0 < total <= 80
    assert all(score.score > 0 for score in scores)


@pytest.mark.asyncio
async def test_score_answer_uses_heuristic_fallback_on_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scoring_agent,
        "llm_complete",
        AsyncMock(side_effect=TimeoutError("timed out")),
    )

    scores, total = await score_answer(
        question="请从个人发展和社会稳定角度谈灵活就业。",
        answer=(
            "首先，灵活就业有利于个人发展。其次，也要看到社保保障不足的问题。"
            "最后，政府应完善制度并规范平台用工。"
        ),
    )

    assert len(scores) == 8
    assert 0 < total <= 80
