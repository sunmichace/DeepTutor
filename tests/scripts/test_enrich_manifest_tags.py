from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "enrich_manifest_tags.py"
    spec = importlib.util.spec_from_file_location("enrich_manifest_tags_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_derive_tags_recognises_question_type_from_path():
    mod = _load_module()
    entry = {
        "file_name": "第11节：解决社会现象类题目.pdf",
        "relative_path": "input/09.老夏说面试/老夏说公务员面试：从小白到面霸课堂笔记/第11节：解决社会现象类题目.pdf",
    }
    tags = mod.derive_tags(entry)
    assert tags["estimated_question_type"] == "社会现象"
    assert tags["estimated_position"] == "公务员"


def test_derive_tags_falls_back_to_default_when_no_signal():
    mod = _load_module()
    tags = mod.derive_tags({"file_name": "untitled.pdf", "relative_path": "untitled.pdf"})
    assert "estimated_question_type" not in tags
    assert "estimated_position" not in tags
    assert "estimated_difficulty" not in tags


def test_inherit_ocr_from_source_backfills_empty_child_tags():
    mod = _load_module()
    files = [
        {
            "file_name": "面试真题200例-上.pdf",
            "source_kind": "original_raw",
            "estimated_question_type": "真题",
            "estimated_position": "公务员",
            "estimated_difficulty": "hard",
            "estimated_content_type": "真题汇编",
        },
        {
            "file_name": "面试真题200例-上__ocr_p3-4.md",
            "source_kind": "derived_ocr",
            "estimated_question_type": "",
            "estimated_position": "通用",
            "estimated_difficulty": "medium",
            "estimated_content_type": "",
        },
    ]
    changed = mod._inherit_ocr_from_source(files)
    assert changed == 4
    child = files[1]
    assert child["estimated_question_type"] == "真题"
    assert child["estimated_position"] == "公务员"
    assert child["estimated_difficulty"] == "hard"
    assert child["estimated_content_type"] == "真题汇编"


def test_inherit_ocr_from_source_does_not_overwrite_strong_child_value():
    mod = _load_module()
    files = [
        {
            "file_name": "X.pdf",
            "source_kind": "original_raw",
            "estimated_question_type": "真题",
            "estimated_difficulty": "hard",
        },
        {
            "file_name": "X__ocr_p0-1.md",
            "source_kind": "derived_ocr",
            "estimated_question_type": "示范作答",
            "estimated_difficulty": "easy",
        },
    ]
    changed = mod._inherit_ocr_from_source(files)
    assert changed == 0
    child = files[1]
    assert child["estimated_question_type"] == "示范作答"
    assert child["estimated_difficulty"] == "easy"


def test_inherit_ocr_from_source_skips_orphans():
    mod = _load_module()
    files = [
        {
            "file_name": "孤儿__ocr_p0-1.md",
            "source_kind": "derived_ocr",
            "estimated_question_type": "",
        },
    ]
    changed = mod._inherit_ocr_from_source(files)
    assert changed == 0
    assert files[0]["estimated_question_type"] == ""
