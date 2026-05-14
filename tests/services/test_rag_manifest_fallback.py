"""Tests for metadata fallback when vector RAG is unavailable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.rag import service as rag_service_module
from deeptutor.services.rag.service import RAGService


@pytest.mark.asyncio
async def test_rag_search_uses_manifest_fallback_when_pipeline_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "interview_bank"
    kb_dir.mkdir()
    (kb_dir / "manifest.json").write_text(
        json.dumps(
            {
                "kb_name": "interview_bank",
                "files": [
                    {
                        "file_name": "综合分析真题100题.pdf",
                        "relative_path": "input/综合分析真题100题.pdf",
                        "estimated_content_type": "真题",
                        "estimated_question_type": "综合分析",
                        "estimated_position": "通用",
                        "estimated_difficulty": "medium",
                        "size": 100,
                    },
                    {
                        "file_name": "计划组织方法论.pdf",
                        "relative_path": "input/计划组织方法论.pdf",
                        "estimated_content_type": "方法论",
                        "estimated_question_type": "计划组织",
                        "estimated_position": "通用",
                        "estimated_difficulty": "medium",
                        "size": 200,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def _raise_missing_pipeline(*args, **kwargs):
        raise RuntimeError("No module named 'llama_index'")

    monkeypatch.setattr(rag_service_module, "get_pipeline", _raise_missing_pipeline)
    rag = RAGService(kb_base_dir=str(tmp_path), provider="llamaindex")

    result = await rag.search("综合分析 面试题", kb_name="interview_bank")

    assert result["fallback"] is True
    assert result["provider"] == "manifest_fallback"
    assert "综合分析真题100题.pdf" in result["content"]
    assert result["sources"][0]["content_type"] == "真题"
