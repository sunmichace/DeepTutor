from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "audit_manifest_tags.py"
    spec = importlib.util.spec_from_file_location("audit_manifest_tags_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SAMPLE_FILES = [
    {
        "file_name": "母题.pdf",
        "relative_path": "input/母题.pdf",
        "source_kind": "original_raw",
        "estimated_question_type": "母题",
        "estimated_position": "公务员",
        "estimated_difficulty": "easy",
        "estimated_content_type": "方法论",
    },
    {
        "file_name": "示范作答100题.pdf",
        "relative_path": "input/示范作答100题.pdf",
        "source_kind": "original_raw",
        "estimated_question_type": "示范作答",
        "estimated_position": "公务员",
        "estimated_difficulty": "hard",
        "estimated_content_type": "方法论",
    },
    {
        "file_name": "无标签.pdf",
        "relative_path": "input/无标签.pdf",
        "source_kind": "original_raw",
        "estimated_question_type": "",
        "estimated_position": "通用",
        "estimated_difficulty": "medium",
        "estimated_content_type": "",
    },
]


def test_coverage_counts_non_default_values():
    mod = _load_module()
    cov = mod._coverage(_SAMPLE_FILES, "estimated_question_type")
    assert cov["total"] == 3
    assert cov["non_default"] == 2
    assert cov["non_default_ratio"] == round(2 / 3, 3)


def test_coverage_treats_default_position_as_default():
    mod = _load_module()
    cov = mod._coverage(_SAMPLE_FILES, "estimated_position")
    # "通用" counts as default; only two rows are tagged specifically.
    assert cov["non_default"] == 2


def test_suspicious_rows_flag_generic_question_types_and_defaults():
    mod = _load_module()
    suspicious = mod._suspicious_rows([
        {
            "file_name": "综合课程.pdf",
            "source_kind": "original_raw",
            "estimated_question_type": "综合课程",
            "estimated_position": "公务员",
            "estimated_difficulty": "medium",
        },
        {
            "file_name": "default_position.pdf",
            "source_kind": "original_raw",
            "estimated_question_type": "真题",
            "estimated_position": "通用",
            "estimated_difficulty": "medium",
        },
    ])
    assert len(suspicious) == 2
    reasons_by_file = {row["file_name"]: row["reasons"] for row in suspicious}
    assert any("generic question_type" in r for r in reasons_by_file["综合课程.pdf"])
    assert any("position is default" in r for r in reasons_by_file["default_position.pdf"])


def test_review_sheet_is_well_formed_markdown():
    mod = _load_module()
    import random

    rng = random.Random(42)
    coverage = {
        field: mod._coverage(_SAMPLE_FILES, field)
        for field in mod.DEFAULT_SENTINELS
    }
    samples = {
        field: mod._stratified_sample(
            _SAMPLE_FILES, field=field, per_bucket=1, rng=rng,
        )
        for field in ("estimated_question_type", "estimated_difficulty", "estimated_position")
    }
    sheet = mod._build_review_sheet(
        _SAMPLE_FILES,
        coverage=coverage,
        suspicious=mod._suspicious_rows(_SAMPLE_FILES),
        samples=samples,
    )

    assert sheet.startswith("# interview_bank manifest tag review")
    assert "## Question type" in sheet
    assert "## Difficulty" in sheet
    assert "## Position" in sheet
    assert "| ☐ |" in sheet
    # Every bucketed row must reference a file from the sample set.
    for file in _SAMPLE_FILES:
        assert file["file_name"] in sheet or file["file_name"] == "无标签.pdf"


def test_audit_end_to_end_writes_both_outputs(tmp_path: Path):
    mod = _load_module()
    manifest = {
        "kb_name": "interview_bank",
        "files": _SAMPLE_FILES,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "report.json"
    review = tmp_path / "review.md"

    import sys
    argv = sys.argv
    sys.argv = [
        "audit_manifest_tags.py",
        "--manifest", str(manifest_path),
        "--output", str(output),
        "--review-md", str(review),
        "--sample-per-bucket", "1",
    ]
    try:
        rc = mod.main()
    finally:
        sys.argv = argv

    assert rc == 0
    assert output.exists() and output.stat().st_size > 0
    assert review.exists() and review.stat().st_size > 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["total_files"] == 3
    assert "coverage" in report
    assert "stratified_samples" in report
