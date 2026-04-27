"""Spike tests for scoring consistency — verifies that the scoring agent
produces stable, sensible scores for the same answer.

This is a live LLM test. It requires LLM configuration.
Marked with pytest.mark.live to allow selective runs.
"""

from __future__ import annotations

import pytest

from deeptutor.agents.interview.scoring_agent import score_answer

pytestmark = pytest.mark.live


@pytest.fixture
def sample_question() -> str:
    return (
        "现在很多年轻人选择灵活就业，你怎么看这种现象？"
        "请从个人发展和社会稳定的角度进行分析。"
    )


@pytest.fixture
def good_answer() -> str:
    return (
        "我认为灵活就业是当前经济社会发展中的一种正常现象，需要辩证看待。\n\n"
        "从积极方面来看：第一，灵活就业体现了就业市场的多元化发展，为年轻人提供了更多职业选择。"
        "第二，互联网平台经济的发展为灵活就业创造了条件，比如自媒体、电商、知识付费等新兴业态。"
        "第三，灵活就业能满足年轻人追求自由、注重工作生活平衡的需求。\n\n"
        "从挑战方面来看：第一，灵活就业存在收入不稳定的问题，缺乏社会保障。"
        "第二，职业发展路径不清晰，缺乏系统的培训和晋升机制。"
        "第三，长期来看可能影响个人的职业积累和专业能力提升。\n\n"
        "从政府角度：第一，应完善灵活就业的社会保障体系，将灵活就业人员纳入社保覆盖范围。"
        "第二，加强职业技能培训，帮助灵活就业人员提升竞争力。"
        "第三，规范平台经济用工关系，保障灵活就业者的合法权益。\n\n"
        "综上所述，灵活就业是时代发展的产物，既要尊重个人选择，也要通过制度完善来保障其健康发展。"
    )


@pytest.fixture
def poor_answer() -> str:
    return (
        "我觉得灵活就业挺好的啊，现在很多人都在家上班。"
        "特别是做直播带货的，收入很高。"
        "我有个朋友做自媒体月入三万。"
        "至于社会稳定什么的，我觉得不是问题吧。"
        "反正年轻人自己选择就行。"
    )


@pytest.mark.flaky(reruns=1)
@pytest.mark.asyncio
async def test_scoring_good_answer_runs(sample_question, good_answer) -> None:
    scores, total = await score_answer(
        question=sample_question,
        answer=good_answer,
        question_type="社会现象类",
        language="zh",
    )
    assert len(scores) == 8, "Should return scores for all 8 dimensions"
    assert 0 < total <= 80, f"Total score should be in (0, 80], got {total}"


@pytest.mark.flaky(reruns=1)
@pytest.mark.asyncio
async def test_scoring_poor_answer_runs(sample_question, poor_answer) -> None:
    scores, total = await score_answer(
        question=sample_question,
        answer=poor_answer,
        question_type="社会现象类",
        language="zh",
    )
    assert len(scores) == 8
    assert 0 < total <= 80


@pytest.mark.flaky(reruns=1)
@pytest.mark.asyncio
async def test_scoring_good_better_than_poor(sample_question, good_answer, poor_answer) -> None:
    """Good answer should score higher than poor answer."""
    _, good_total = await score_answer(
        question=sample_question,
        answer=good_answer,
        language="zh",
    )
    _, poor_total = await score_answer(
        question=sample_question,
        answer=poor_answer,
        language="zh",
    )
    assert good_total > poor_total, (
        f"Good answer ({good_total}) should score higher than poor answer ({poor_total})"
    )


@pytest.mark.flaky(reruns=2)
@pytest.mark.asyncio
async def test_scoring_consistency_across_runs(sample_question, good_answer) -> None:
    """Score the same answer 3 times and verify scores are within tolerance."""
    results = []
    for _ in range(3):
        scores, total = await score_answer(
            question=sample_question,
            answer=good_answer,
            language="zh",
        )
        results.append(total)

    max_diff = max(results) - min(results)
    assert max_diff <= 15, (
        f"Scores across 3 runs varied by {max_diff} points: {results}. "
        f"Expected max difference ≤ 15."
    )
