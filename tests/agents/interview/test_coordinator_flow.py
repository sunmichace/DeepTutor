"""Tests for MockInterviewCoordinator data flow logic.

These tests verify the state machine transitions and data integrity
without calling actual LLM APIs (using monkeypatch/mocks).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.agents.interview.coordinator import (
    MockInterviewCoordinator,
    _extract_training_suggestion,
)
from deeptutor.agents.interview.followup_agent import _parse_followup_decision
from deeptutor.agents.interview.memory_writer import write_session_to_memory
from deeptutor.agents.interview.models import InterviewSession, InterviewTurn, DimensionScore
from deeptutor.services.interview import (
    InterviewMemoryService,
    LearnerProfile,
    StableProfile,
    reset_interview_memory_instances,
)


@pytest.fixture(autouse=True)
def reset():
    reset_interview_memory_instances()
    yield


@pytest.fixture
def coordinator():
    return MockInterviewCoordinator(user_id="test_user", language="zh")


def test_initial_state(coordinator):
    assert coordinator.state == "idle"
    assert coordinator.session is None


def test_parse_followup_decision_prefers_final_explicit_token():
    assert _parse_followup_decision("分析过程... NO") is False
    assert _parse_followup_decision("分析过程... YES") is True
    assert _parse_followup_decision("不需要追问") is False
    assert _parse_followup_decision("建议继续追问") is True
    assert _parse_followup_decision("") is False


@pytest.mark.asyncio
async def test_start_interview_no_rag(coordinator):
    """start_interview should work even without RAG (uses fallback question)."""
    result = await coordinator.start_interview(
        exam_type="公考面试",
        position="综合管理",
        question_type="综合分析",
        difficulty="medium",
    )
    assert result["state"] == "questioning"
    assert "session_id" in result
    assert result["question"]
    assert coordinator.session is not None
    assert coordinator.session.question_type == "综合分析"
    assert coordinator.session.position == "综合管理"


@pytest.mark.asyncio
async def test_start_interview_profile_read(coordinator):
    """start_interview should read user profile for context."""
    # Pre-set a profile
    svc = InterviewMemoryService("test_user")
    svc.save_profile(LearnerProfile(
        stable=StableProfile(target_exam_type="国考", target_position="税务"),
    ))

    result = await coordinator.start_interview(question_type="综合分析")
    assert result["examiner_context"]
    assert "税务" in result["examiner_context"] or "国考" in result["examiner_context"]


@pytest.mark.asyncio
async def test_start_interview_uses_question_fallback_for_manifest_fallback():
    rag = AsyncMock()
    rag.search.return_value = {
        "content": "向量索引暂不可用，以下为知识库 manifest 元数据检索结果：\n1. 面试真题200例-上.pdf",
        "fallback": True,
        "provider": "manifest_fallback",
    }
    coord = MockInterviewCoordinator(user_id="fallback_user", rag_service=rag)

    result = await coord.start_interview(
        position="税务",
        question_type="综合分析",
    )

    assert "向量索引暂不可用" not in result["question"]
    assert "综合分析" in result["question"]
    assert "税务" in result["question"]


@pytest.mark.asyncio
async def test_start_interview_uses_question_fallback_for_empty_vector_index():
    rag = AsyncMock()
    rag.search.return_value = {
        "content": "",
        "answer": "No documents indexed. Please upload documents first.",
        "provider": "llamaindex",
    }
    coord = MockInterviewCoordinator(user_id="empty_index_user", rag_service=rag)

    result = await coord.start_interview(
        position="税务",
        question_type="综合分析",
    )

    assert "No documents indexed" not in result["question"]
    assert "综合分析" in result["question"]
    assert "税务" in result["question"]


@pytest.mark.asyncio
async def test_start_interview_uses_question_fallback_for_search_error_content():
    rag = AsyncMock()
    rag.search.return_value = {
        "content": "",
        "answer": "Search failed: CUDA error: out of memory",
        "provider": "llamaindex",
    }
    coord = MockInterviewCoordinator(user_id="search_error_user", rag_service=rag)

    result = await coord.start_interview(
        position="基层治理",
        question_type="综合分析",
    )

    assert "Search failed" not in result["question"]
    assert "out of memory" not in result["question"]
    assert "综合分析" in result["question"]
    assert "基层治理" in result["question"]


@pytest.mark.asyncio
async def test_start_interview_does_not_use_raw_long_rag_material_as_question():
    rag = AsyncMock()
    rag.search.return_value = {
        "content": (
            "【论证分析】\n"
            "自治、法治、德治，法治是基层治理的基石。总书记提出，要把依法治国理念贯穿于基层治理的始终。"
            "如果此次活动交给我负责，我会结合八五普法要求开展宣传。\n"
            "一是前期准备要充分。\n"
            "二是人员参与要丰富。\n\n"
            "主管部门要组织全区专项整治，如果交给你负责，你如果组织？"
        ),
        "sources": [{"title": "论证分析-基层治理.doc"}],
        "provider": "llamaindex",
    }
    coord = MockInterviewCoordinator(user_id="rag_material_user", rag_service=rag)

    result = await coord.start_interview(
        position="基层治理",
        question_type="综合分析",
    )

    assert len(result["question"]) < 300
    assert "一是前期准备要充分" not in result["question"]
    assert "主管部门要组织全区专项整治" not in result["question"]
    assert "基层治理" in result["question"]
    assert "综合分析" in result["question"]


@pytest.mark.asyncio
async def test_start_interview_uses_short_question_like_rag_content():
    rag = AsyncMock()
    rag.search.return_value = {
        "content": "请谈谈你对基层治理中法治建设的理解？\n参考答案：第一，要依法办事。",
        "provider": "llamaindex",
    }
    coord = MockInterviewCoordinator(user_id="rag_question_user", rag_service=rag)

    result = await coord.start_interview(
        position="基层治理",
        question_type="综合分析",
    )

    assert result["question"] == "请谈谈你对基层治理中法治建设的理解"


def test_extract_training_suggestion_prefers_explicit_section_over_table_advice():
    review = """
### 各维度评分分析

| 维度 | 得分 | 扣分原因分析 | 改进建议 |
| :--- | :--- | :--- | :--- |
| **岗位匹配度** | **8.0** | 职责挖掘不够 | 增加岗位案例 |

### 下一步训练建议

围绕基层治理主题积累2-3个具体案例，并练习用“是什么、为什么、怎么办”展开。

### 结束语
继续训练。
"""

    assert _extract_training_suggestion(review) == (
        "围绕基层治理主题积累2-3个具体案例，并练习用“是什么、为什么、怎么办”展开。"
    )


def test_extract_training_suggestion_supports_inline_section_heading():
    assert (
        _extract_training_suggestion("复盘报告。\n下一步训练建议：继续练习综合分析。")
        == "继续练习综合分析。"
    )


def test_extract_training_suggestion_fallback_ignores_trailing_heading():
    review = """
### 主要扣分原因

案例说服力不足，需要补充具体场景。

#### 4. 追问表现评估
"""

    assert _extract_training_suggestion(review) == "案例说服力不足，需要补充具体场景。"


def test_extract_training_suggestion_ignores_truncated_bold_heading_fragment():
    review = """
#### 3. 主要扣分原因

1. **审题立意偏差**：将题目理解成了基层治理执行题。

#### 4. 追问表现评估

**评估结果
"""

    assert _extract_training_suggestion(review) == ""


@pytest.mark.asyncio
async def test_submit_answer_without_session(coordinator):
    """Submitting an answer without starting should return an error."""
    result = await coordinator.submit_answer("test answer")
    assert "error" in result


@pytest.mark.asyncio
async def test_cancel(coordinator):
    await coordinator.start_interview()
    result = await coordinator.cancel()
    assert result["state"] == "cancelled"


@pytest.mark.asyncio
async def test_full_flow_prefers_json_training_suggestion_over_text_section(coordinator):
    """End-to-end: when the LLM review emits a JSON block, coordinator uses it.

    Verifies the structured fallback chain: TrainingSuggestionPayload (JSON)
    wins over the text section "下一步训练建议", which in turn wins over the
    score-based fallback.
    """
    review_with_json = (
        "本次表现总结：整体中规中矩，结构完整但论据偏空。\n\n"
        "下一步训练建议：加强综合分析练习。\n\n"
        "```json\n"
        '{"focus_dimension": "论据与案例质量", '
        '"suggestion": "按题型整理两个税务窗口服务案例。", '
        '"drills": ["STAR 结构复述", "对着镜子 3 分钟速答"]}\n'
        "```"
    )
    with patch(
        "deeptutor.agents.interview.coordinator.should_follow_up",
        AsyncMock(return_value=False),
    ), patch(
        "deeptutor.agents.interview.coordinator.score_answer",
        AsyncMock(return_value=(
            [DimensionScore(dimension=f"维度{i+1}", score=7.0, max_score=10.0) for i in range(8)],
            56.0,
        )),
    ), patch(
        "deeptutor.agents.interview.coordinator.generate_review",
        AsyncMock(return_value=review_with_json),
    ):
        await coordinator.start_interview(question_type="综合分析")
        result = await coordinator.submit_answer("作答内容。")

    session = coordinator.session
    assert session is not None
    suggestion = session.training_suggestion
    # JSON-derived suggestion must win over the plain "下一步训练建议" line.
    assert "加强综合分析练习" not in suggestion
    assert "税务窗口服务案例" in suggestion
    assert "[论据与案例质量]" in suggestion
    assert "STAR" in suggestion
    # submit_answer echoes the final suggestion in its result dict.
    assert result["training_suggestion"] == suggestion


@pytest.mark.asyncio
async def test_full_flow_with_mocked_llm(coordinator):
    """Test the full interview flow with mocked LLM calls."""
    with patch(
        "deeptutor.agents.interview.coordinator.should_follow_up",
        AsyncMock(return_value=False),
    ), patch(
        "deeptutor.agents.interview.coordinator.score_answer",
        AsyncMock(return_value=(
            [DimensionScore(dimension=f"维度{i+1}", score=7.0, max_score=10.0) for i in range(8)],
            56.0,
        )),
    ), patch(
        "deeptutor.agents.interview.coordinator.generate_review",
        AsyncMock(return_value="Mock review report.\n下一步训练建议：加强综合分析练习。"),
    ):
        start = await coordinator.start_interview(question_type="综合分析")
        assert coordinator.state == "questioning"

        result = await coordinator.submit_answer("这是一道综合分析题的作答内容。")
        assert result["state"] == "completed"
        assert result["total_score"] == 56.0
        assert len(result["scores"]) == 8

        session = coordinator.session
        assert session is not None
        assert session.user_answer == "这是一道综合分析题的作答内容。"
        assert session.total_score == 56.0


@pytest.mark.asyncio
async def test_full_flow_uses_score_based_training_suggestion_when_review_truncated(coordinator):
    with patch(
        "deeptutor.agents.interview.coordinator.should_follow_up",
        AsyncMock(return_value=False),
    ), patch(
        "deeptutor.agents.interview.coordinator.score_answer",
        AsyncMock(return_value=(
            [
                DimensionScore(
                    dimension="论据与案例质量",
                    score=5.0,
                    max_score=10.0,
                    deduction_reason="案例不够具体",
                ),
                DimensionScore(
                    dimension="结构化表达",
                    score=8.0,
                    max_score=10.0,
                    deduction_reason="结构基本清晰",
                ),
            ],
            13.0,
        )),
    ), patch(
        "deeptutor.agents.interview.coordinator.generate_review",
        AsyncMock(return_value="### 主要扣分原因\n\n#### 4. 追问表现评估"),
    ):
        await coordinator.start_interview(question_type="综合分析")
        result = await coordinator.submit_answer("回答内容。")

        assert result["state"] == "completed"
        assert result["training_suggestion"] == "重点训练“论据与案例质量”：案例不够具体"


@pytest.mark.asyncio
async def test_full_flow_with_followup(coordinator):
    """Test flow where followup is triggered."""
    with patch(
        "deeptutor.agents.interview.coordinator.should_follow_up",
        AsyncMock(return_value=True),
    ), patch(
        "deeptutor.agents.interview.coordinator.generate_followup",
        AsyncMock(return_value="请具体举例说明。"),
    ), patch(
        "deeptutor.agents.interview.coordinator.score_answer",
        AsyncMock(return_value=(
            [DimensionScore(dimension=f"维度{i+1}", score=6.0, max_score=10.0) for i in range(8)],
            48.0,
        )),
    ), patch(
        "deeptutor.agents.interview.coordinator.generate_review",
        AsyncMock(return_value="Mock review. 建议：加强审题。"),
    ):
        await coordinator.start_interview(question_type="综合分析")
        result = await coordinator.submit_answer("我的初步回答。")
        assert result["state"] == "followup_questioning"
        assert result["needs_followup"] is True

        result2 = await coordinator.submit_followup_answer("具体例子是...")
        assert result2["state"] == "completed"
        assert result2["total_score"] == 48.0


@pytest.mark.asyncio
async def test_submit_followup_without_followup_question(coordinator):
    """submit_followup_answer directly should still work (edge case)."""
    with patch(
        "deeptutor.agents.interview.coordinator.should_follow_up",
        AsyncMock(return_value=False),
    ), patch(
        "deeptutor.agents.interview.coordinator.score_answer",
        AsyncMock(return_value=(
            [DimensionScore(dimension=f"维度{i+1}", score=5.0, max_score=10.0) for i in range(8)],
            40.0,
        )),
    ), patch(
        "deeptutor.agents.interview.coordinator.generate_review",
        AsyncMock(return_value="Review."),
    ):
        await coordinator.start_interview()
        result = await coordinator.submit_answer("回答内容。")
        assert result["state"] == "completed"


@pytest.mark.asyncio
async def test_memory_writer_dedupes_reasons_and_records_sources():
    svc = InterviewMemoryService("writer_test")
    session = InterviewSession(
        session_id="writer_s1",
        user_id="writer_test",
        exam_type="公考面试",
        position="综合管理",
        question_type="综合分析",
        followup_question="请补充具体案例。",
        followup_answer="基层窗口服务案例。",
        total_score=38.0,
        scores=[
            DimensionScore(
                dimension="审题与立意",
                score=4.0,
                max_score=10.0,
                deduction_reason="立意偏浅",
            ),
            DimensionScore(
                dimension="逻辑完整性",
                score=5.0,
                max_score=10.0,
                deduction_reason="立意偏浅",
            ),
        ],
        training_suggestion="补充案例和分析层次。",
    )

    await write_session_to_memory(session=session, memory_service=svc)
    profile = svc.read_profile()

    assert profile.dynamic.recent_deduction_reasons == ["立意偏浅"]
    assert profile.dynamic.recent_low_score_dimensions[0]["session_id"] == "writer_s1"
    assert profile.dynamic.recent_low_score_dimensions[0]["question_type"] == "综合分析"
    assert profile.dynamic.recent_followup_issues == [
        "综合分析追问已完成：请补充具体案例。"
    ]


@pytest.mark.asyncio
async def test_memory_writer_builds_multi_session_profile_trends():
    svc = InterviewMemoryService("trend_writer_test")

    first = InterviewSession(
        session_id="trend_s1",
        user_id="trend_writer_test",
        exam_type="公考面试",
        position="综合管理",
        question_type="综合分析",
        total_score=52.0,
        completed_at="2026-05-01T10:00:00+08:00",
        scores=[
            DimensionScore(
                dimension="论据与案例质量",
                score=4.0,
                max_score=10.0,
                deduction_reason="案例不足",
            ),
            DimensionScore(dimension="结构化表达", score=7.0, max_score=10.0),
        ],
        training_suggestion="积累基层治理案例。",
    )
    second = InterviewSession(
        session_id="trend_s2",
        user_id="trend_writer_test",
        exam_type="公考面试",
        position="综合管理",
        question_type="计划组织",
        total_score=46.0,
        completed_at="2026-05-02T10:00:00+08:00",
        scores=[
            DimensionScore(
                dimension="论据与案例质量",
                score=5.0,
                max_score=10.0,
                deduction_reason="案例不够具体",
            ),
            DimensionScore(dimension="结构化表达", score=6.0, max_score=10.0),
        ],
        training_suggestion="按题型整理2个可复用案例。",
    )
    latest = InterviewSession(
        session_id="trend_s3",
        user_id="trend_writer_test",
        exam_type="公考面试",
        position="综合管理",
        question_type="综合分析",
        total_score=42.0,
        completed_at="2026-05-03T10:00:00+08:00",
        scores=[
            DimensionScore(
                dimension="论据与案例质量",
                score=5.0,
                max_score=10.0,
                deduction_reason="案例仍偏空",
            ),
            DimensionScore(
                dimension="结构化表达",
                score=5.0,
                max_score=10.0,
                deduction_reason="结构层次不够清楚",
            ),
        ],
        training_suggestion="重点训练案例展开和结构分层。",
    )

    await write_session_to_memory(session=first, memory_service=svc)
    await write_session_to_memory(session=second, memory_service=svc)
    await write_session_to_memory(session=latest, memory_service=svc)

    profile = svc.read_profile()

    repeated = profile.dynamic.repeated_weak_dimensions
    assert repeated[0]["dimension"] == "论据与案例质量"
    assert repeated[0]["count"] == 3
    assert repeated[0]["latest_session_id"] == "trend_s3"
    assert profile.dynamic.recent_weak_types[:2] == ["综合分析", "计划组织"]
    assert profile.dynamic.training_suggestion_history[0]["session_id"] == "trend_s3"
    assert profile.dynamic.current_training_suggestion == "重点训练案例展开和结构分层。"
    assert "下降" in profile.dynamic.recent_trend

    trend_by_dimension = {
        item["dimension"]: item
        for item in profile.dynamic.dimension_trends
    }
    assert trend_by_dimension["结构化表达"]["status"] == "declining"
    assert trend_by_dimension["论据与案例质量"]["status"] == "persistently_weak"


def test_log_rag_provenance_includes_manifest_tags():
    from deeptutor.agents.interview import coordinator

    coordinator._MANIFEST_CACHE["interview_bank"] = {
        "面试真题200例-上__ocr_p10-11.md": {
            "source_kind": "derived_ocr",
            "estimated_question_type": "真题",
            "estimated_difficulty": "hard",
            "estimated_position": "公务员",
        },
        "03.老夏真题100题.pdf": {
            "source_kind": "original_raw",
            "estimated_question_type": "真题",
            "estimated_difficulty": "hard",
            "estimated_position": "公务员",
        },
    }
    try:
        with patch.object(coordinator.logger, "info") as mock_info:
            coordinator._log_rag_provenance(
                query="社会现象 面试题 公务员 medium",
                question_type="社会现象",
                difficulty="medium",
                position="公务员",
                result={
                    "sources": [
                        {"title": "面试真题200例-上__ocr_p10-11.md", "score": 0.85},
                        {"title": "03.老夏真题100题.pdf", "score": 0.72},
                    ],
                    "fallback": False,
                },
            )

        assert mock_info.call_count == 1
        message = mock_info.call_args.args[0]
        assert "kind=derived_ocr" in message
        assert "kind=original_raw" in message
        assert "qt=真题" in message
        assert "diff=hard" in message
        assert "hits=2" in message
        assert "fallback=False" in message
    finally:
        coordinator._MANIFEST_CACHE.pop("interview_bank", None)


def test_log_rag_provenance_handles_empty_sources():
    from deeptutor.agents.interview import coordinator

    with patch.object(coordinator.logger, "info") as mock_info:
        coordinator._log_rag_provenance(
            query="人际关系 面试题 公务员",
            question_type="人际关系",
            difficulty="",
            position="公务员",
            result={"sources": [], "fallback": True},
        )

    assert mock_info.call_count == 1
    message = mock_info.call_args.args[0]
    assert "sources=0" in message
    assert "fallback=True" in message


def test_extract_training_suggestion_payload_parses_valid_json():
    from deeptutor.agents.interview.review_agent import extract_training_suggestion_payload

    review = """本次表现总结：...

下一步训练建议：加强案例展开。

```json
{
  "focus_dimension": "论据与案例质量",
  "suggestion": "补充基层治理案例，每题至少展开 2 个具体事例。",
  "drills": ["整理 2 个税务窗口服务案例", "用 STAR 结构复述"]
}
```
"""
    payload = extract_training_suggestion_payload(review)
    assert payload is not None
    assert payload.focus_dimension == "论据与案例质量"
    assert "基层治理案例" in payload.suggestion
    assert len(payload.drills) == 2

    text = payload.to_text()
    assert text.startswith("[论据与案例质量]")
    assert "补充基层治理案例" in text
    assert "STAR" in text


def test_extract_training_suggestion_payload_returns_none_on_malformed_json():
    from deeptutor.agents.interview.review_agent import extract_training_suggestion_payload

    review = """下一步训练建议：加强案例展开。

```json
{ not valid json
```
"""
    assert extract_training_suggestion_payload(review) is None


def test_extract_training_suggestion_payload_returns_none_without_block():
    from deeptutor.agents.interview.review_agent import extract_training_suggestion_payload

    review = "下一步训练建议：加强案例展开。"
    assert extract_training_suggestion_payload(review) is None


def test_extract_training_suggestion_payload_rejects_oversize_fields():
    from deeptutor.agents.interview.review_agent import extract_training_suggestion_payload

    long_suggestion = "x" * 500
    review = f"""
```json
{{"focus_dimension": "论据与案例质量", "suggestion": "{long_suggestion}", "drills": []}}
```
"""
    assert extract_training_suggestion_payload(review) is None


def test_clamp_review_length_is_noop_when_under_cap():
    from deeptutor.agents.interview.review_agent import clamp_review_length

    review = "短报告。\n\n下一步训练建议：多练。"
    assert clamp_review_length(review) == review


def test_clamp_review_length_preserves_opening_suggestion_and_json():
    from deeptutor.agents.interview.review_agent import clamp_review_length

    filler = "填充段落。" * 400  # ~2000 chars of middle noise
    review = (
        "本次表现总结：整体中规中矩，结构完整但论据偏空。\n\n"
        "各维度评分分析：\n"
        f"{filler}\n\n"
        "主要扣分原因：案例空、逻辑断层。\n\n"
        "下一步训练建议：按题型整理两个可复用案例，练 STAR 结构。\n\n"
        "```json\n"
        '{"focus_dimension": "论据与案例质量", "suggestion": "补案例", "drills": ["STAR"]}\n'
        "```"
    )

    trimmed = clamp_review_length(review, hard_cap=1200)
    assert len(trimmed) <= 1200
    assert "本次表现总结" in trimmed
    assert "下一步训练建议" in trimmed
    assert "```json" in trimmed
    assert "STAR" in trimmed


def test_clamp_review_length_handles_missing_sections():
    from deeptutor.agents.interview.review_agent import clamp_review_length

    review = "这是一份非常长的、没有任何小标题的流水账。" * 200
    trimmed = clamp_review_length(review, hard_cap=300)
    assert len(trimmed) <= 300
    assert trimmed.startswith("这是一份非常长的")


@pytest.mark.asyncio
async def test_select_question_calls_picker_and_reranks_sources():
    """End-to-end: picker hints flow into RAG query and reorder sources.

    Verifies the full integration: profile → resolve_picker_hints → query
    augmentation → RAG.search → filter_and_rerank → picker_hints +
    rag_provenance log emission, in the right order.
    """
    from deeptutor.agents.interview import coordinator
    from deeptutor.agents.interview.coordinator import MockInterviewCoordinator
    from deeptutor.agents.interview.memory_writer import write_session_to_memory
    from deeptutor.agents.interview.models import DimensionScore, InterviewSession

    coord = MockInterviewCoordinator(user_id="picker_e2e_user")

    # Seed two low-score sessions on 论据与案例质量 to populate
    # repeated_weak_dimensions + recent_weak_types in the dynamic profile.
    for sid, qt in (("e2e_s1", "综合分析"), ("e2e_s2", "社会现象")):
        await write_session_to_memory(
            session=InterviewSession(
                session_id=sid,
                user_id="picker_e2e_user",
                exam_type="公考面试",
                position="公务员",
                question_type=qt,
                difficulty="medium",
                total_score=42.0,
                completed_at=f"2026-05-01T10:0{sid[-1]}:00+08:00",
                training_suggestion="补充基层治理案例。",
                scores=[
                    DimensionScore(
                        dimension="论据与案例质量",
                        score=4.0,
                        max_score=10.0,
                        deduction_reason="案例不足",
                    ),
                ],
            ),
            memory_service=coord._memory,
        )

    captured_query: dict[str, str] = {}

    async def _fake_search(*, query: str, kb_name: str, **kwargs):
        captured_query["query"] = query
        return {
            "content": "请谈谈你怎么看待基层治理中的论据缺失问题？",
            "answer": "请谈谈你怎么看待基层治理中的论据缺失问题？",
            "fallback": False,
            "sources": [
                {"title": "通用模块.pdf", "score": 0.80},
                {"title": "社会现象真题.pdf", "score": 0.70},
            ],
        }

    coord._rag.search = _fake_search  # type: ignore[method-assign]
    coordinator._MANIFEST_CACHE["interview_bank"] = {
        "通用模块.pdf": {
            "source_kind": "original_raw",
            "estimated_question_type": "基础",
            "estimated_difficulty": "easy",
        },
        "社会现象真题.pdf": {
            "source_kind": "original_raw",
            "estimated_question_type": "社会现象",
            "estimated_difficulty": "medium",
        },
    }

    try:
        with patch.object(coordinator.logger, "info") as mock_info:
            await coord.start_interview(question_type="综合分析", position="公务员")

        # Query must include the focus dimension and a fragment of the
        # active suggestion that the picker derived from past sessions.
        assert "论据与案例质量" in captured_query["query"]
        assert "补充基层治理案例" in captured_query["query"]

        log_messages = [call.args[0] for call in mock_info.call_args_list]
        picker_logs = [m for m in log_messages if m.startswith("picker_hints")]
        provenance_logs = [m for m in log_messages if m.startswith("rag_provenance")]
        assert picker_logs, f"expected picker_hints log, got {log_messages}"
        assert provenance_logs, f"expected rag_provenance log, got {log_messages}"

        # picker_hints must come before rag_provenance.
        assert log_messages.index(picker_logs[0]) < log_messages.index(provenance_logs[0])

        # Provenance must show the reranked order: 社会现象 (focus + diff match) > 通用.
        provenance = provenance_logs[0]
        assert provenance.index("社会现象真题.pdf") < provenance.index("通用模块.pdf")
        assert "kind=original_raw" in provenance

        # picker_snapshot is persisted on the session for offline auditing.
        session = coord.session
        assert session is not None
        snapshot = session.picker_snapshot
        assert snapshot, "picker_snapshot must be populated"
        assert snapshot["source_kind"] == "rag"
        assert snapshot["effective_difficulty"] == "medium"
        assert snapshot["hints"]["focus_dimensions"] == ["论据与案例质量"]
        assert "论据与案例质量" in snapshot["query"]
        assert snapshot["reranked_sources"], "reranked_sources should not be empty"
        assert snapshot["reranked_sources"][0]["title"] == "社会现象真题.pdf"
    finally:
        coordinator._MANIFEST_CACHE.pop("interview_bank", None)


def test_interview_session_round_trips_picker_snapshot():
    from deeptutor.agents.interview.models import InterviewSession

    payload = {
        "hints": {"focus_dimensions": ["论据与案例质量"], "reason": "focus_dim=..."},
        "requested_difficulty": "medium",
        "effective_difficulty": "hard",
        "source_kind": "rag",
        "reranked_sources": [{"title": "社会现象真题.pdf", "score": 0.95}],
        "query": "综合分析 面试题 公务员 hard 论据与案例质量",
    }
    session = InterviewSession(
        session_id="rt-1",
        user_id="rt-user",
        picker_snapshot=payload,
    )
    restored = InterviewSession.from_dict(session.to_dict())
    assert restored.picker_snapshot == payload


def test_interview_session_from_dict_defaults_missing_picker_snapshot():
    from deeptutor.agents.interview.models import InterviewSession

    legacy = {"session_id": "legacy-1", "user_id": "legacy-user"}
    restored = InterviewSession.from_dict(legacy)
    assert restored.picker_snapshot == {}
