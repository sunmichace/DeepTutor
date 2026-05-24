"""Tests for interview data ingestion script guardrails."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_ingest_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "ingest_interview_data.py"
    spec = importlib.util.spec_from_file_location("ingest_interview_data_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_categorize_file_detects_content_type_question_type_and_position(tmp_path: Path) -> None:
    ingest = _load_ingest_module()
    source = tmp_path / "input" / "广东资料" / "【计划组织专项】广东选调面试小班带练课.pdf"
    source.parent.mkdir(parents=True)
    source.write_text("dummy", encoding="utf-8")

    result = ingest.categorize_file(source)

    assert result["file_name"] == source.name
    assert result["estimated_content_type"] == "方法论"
    assert result["estimated_question_type"] == "计划组织"
    assert result["estimated_position"] == "综合管理"
    assert result["estimated_difficulty"] == "medium"


def test_categorize_file_detects_material_content_types(tmp_path: Path) -> None:
    ingest = _load_ingest_module()
    cases = [
        ("面试真题200例.pdf", "真题"),
        ("高分学员笔记.pdf", "高分作答"),
        ("热点押题材料.pdf", "热点材料"),
        ("论证素材总结.doc", "论证素材"),
        ("结构化面试示范作答.pdf", "示范表达"),
    ]

    for filename, expected in cases:
        source = tmp_path / "input" / filename
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("dummy", encoding="utf-8")
        assert ingest.categorize_file(source)["estimated_content_type"] == expected


@pytest.mark.asyncio
async def test_ingest_skips_rag_initialization_when_embedding_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ingest = _load_ingest_module()
    project_root = tmp_path
    input_dir = project_root / "input"
    input_dir.mkdir()
    (input_dir / "面试真题.txt").write_text("请谈谈你对基层治理的理解。", encoding="utf-8")

    monkeypatch.setattr(ingest, "_PROJECT_ROOT", project_root)

    async def fake_health(_sample_text: str):
        return SimpleNamespace(
            ok=False,
            binding="custom",
            model="deepseek-embedding",
            base_url="https://api.deepseek.com/v1",
            error="HTTPStatusError: 404 Not Found",
            suggestion="Configure a real embedding provider.",
        )

    class FailingRAGService:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("RAGService should not be initialized")

    monkeypatch.setattr("deeptutor.services.embedding.health.check_embedding_health", fake_health)
    monkeypatch.setattr("deeptutor.services.rag.service.RAGService", FailingRAGService)

    ok = await ingest.ingest_to_knowledge_base(kb_name="interview_bank")

    assert ok is True
    kb_dir = project_root / "data" / "knowledge_bases" / "interview_bank"
    assert (kb_dir / "raw" / "面试真题.txt").exists()
    manifest = json.loads((kb_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_files"] == 1


@pytest.mark.asyncio
async def test_ingest_can_skip_embedding_check_and_initialize_rag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ingest = _load_ingest_module()
    project_root = tmp_path
    input_dir = project_root / "input"
    input_dir.mkdir()
    source = input_dir / "面试真题.txt"
    source.write_text("请谈谈你对基层治理的理解。", encoding="utf-8")

    monkeypatch.setattr(ingest, "_PROJECT_ROOT", project_root)
    calls: list[dict] = []

    class FakeRAGService:
        def __init__(self, *args, **kwargs) -> None:
            calls.append({"init_args": args, "init_kwargs": kwargs})

        async def initialize(self, *, kb_name: str, file_paths: list[str], **kwargs) -> bool:
            calls.append({"kb_name": kb_name, "file_paths": file_paths})
            return True

    monkeypatch.setattr("deeptutor.services.rag.service.RAGService", FakeRAGService)

    ok = await ingest.ingest_to_knowledge_base(
        kb_name="interview_bank",
        skip_embedding_check=True,
    )

    assert ok is True
    assert calls[-1]["kb_name"] == "interview_bank"
    assert calls[-1]["file_paths"] == [str(source)]
