from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def _load_ocr_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "ocr_interview_pdfs.py"
    spec = importlib.util.spec_from_file_location("ocr_interview_pdfs_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_ocr_uses_mineru_safe_defaults_and_copies_markdown(monkeypatch, tmp_path: Path):
    ocr = _load_ocr_module()
    source = tmp_path / "示范作答.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    output_dir = tmp_path / "ocr_text"
    calls = []

    monkeypatch.setattr(ocr, "_mineru_command", lambda: "mineru")

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        mineru_output = Path(cmd[cmd.index("-o") + 1])
        generated = mineru_output / source.stem / "ocr"
        generated.mkdir(parents=True)
        (generated / f"{source.stem}.md").write_text("# 题目\n\n示范作答内容", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ocr.subprocess, "run", fake_run)

    result = ocr.run_ocr(
        pdf=source,
        output_dir=output_dir,
        start=2,
        end=3,
        lang="ch",
        device="cpu",
        keep_runs=False,
        dry_run=False,
    )

    assert result["ok"] is True
    assert result["chars"] == len("# 题目\n\n示范作答内容")
    assert result["engine"] == "mineru"
    assert result["page_range"] == "p2-3"
    assert result["quality_status"] == "usable"
    assert result["formula"] is False
    assert result["table"] is False
    assert calls
    assert calls[0] == [
        "mineru",
        "-p",
        str(source),
        "-o",
        str(output_dir / "_mineru_runs" / "示范作答__p2-3"),
        "-m",
        "ocr",
        "-b",
        "pipeline",
        "-l",
        "ch",
        "-d",
        "cpu",
        "-f",
        "false",
        "-t",
        "false",
        "-s",
        "2",
        "-e",
        "3",
    ]

    artifact = output_dir / "示范作答__ocr_p2-3.md"
    text = artifact.read_text(encoding="utf-8")
    assert "OCR derived from: 示范作答.pdf" in text
    assert "page_range: p2-3" in text
    assert "示范作答内容" in text
    assert not (output_dir / "_mineru_runs" / "示范作答__p2-3").exists()


def test_run_ocr_can_keep_mineru_runs_for_debug(monkeypatch, tmp_path: Path):
    ocr = _load_ocr_module()
    source = tmp_path / "调试样本.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    output_dir = tmp_path / "ocr_text"

    monkeypatch.setattr(ocr, "_mineru_command", lambda: "mineru")

    def fake_run(cmd, check, capture_output, text):
        mineru_output = Path(cmd[cmd.index("-o") + 1])
        generated = mineru_output / source.stem / "ocr"
        generated.mkdir(parents=True)
        (generated / f"{source.stem}.md").write_text("调试内容", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ocr.subprocess, "run", fake_run)

    result = ocr.run_ocr(
        pdf=source,
        output_dir=output_dir,
        start=0,
        end=1,
        lang="ch",
        device="cpu",
        keep_runs=True,
        dry_run=False,
    )

    assert result["ok"] is True
    assert (output_dir / "_mineru_runs" / "调试样本__p0-1").exists()


def test_write_manifest_records_counts(tmp_path: Path):
    ocr = _load_ocr_module()
    manifest = ocr._write_manifest(
        tmp_path,
        [
            {"ok": True, "artifact": "a.md"},
            {"ok": False, "artifact": "b.md"},
        ],
    )

    text = manifest.read_text(encoding="utf-8")
    assert '"total": 2' in text
    assert '"ok": 1' in text
    assert '"artifact": "a.md"' in text


def test_write_manifest_appends_and_replaces_same_pdf_range(tmp_path: Path):
    ocr = _load_ocr_module()
    ocr._write_manifest(
        tmp_path,
        [
            {
                "source_pdf": "a.pdf",
                "start": 0,
                "end": 1,
                "ok": True,
                "artifact": "old.md",
            }
        ],
    )
    manifest = ocr._write_manifest(
        tmp_path,
        [
            {
                "source_pdf": "a.pdf",
                "start": 0,
                "end": 1,
                "ok": True,
                "artifact": "new.md",
            },
            {
                "source_pdf": "b.pdf",
                "start": 2,
                "end": 3,
                "ok": True,
                "artifact": "b.md",
            },
        ],
    )

    text = manifest.read_text(encoding="utf-8")
    assert '"total": 2' in text
    assert '"ok": 2' in text
    assert "new.md" in text
    assert "old.md" not in text
    assert "b.md" in text


def test_sync_ocr_manifest_to_kb_manifest_adds_derived_records(tmp_path: Path):
    ocr = _load_ocr_module()
    base_dir = tmp_path / "knowledge_bases"
    kb_dir = base_dir / "interview_bank"
    raw_dir = kb_dir / "raw"
    output_dir = kb_dir / "ocr_text"
    storage_dir = kb_dir / "llamaindex_storage"
    raw_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    storage_dir.mkdir(parents=True)

    source_pdf = raw_dir / "示范作答.pdf"
    source_pdf.write_bytes(b"%PDF-1.7\n")
    artifact = output_dir / "示范作答__ocr_p0-1.md"
    artifact.write_text("OCR 文本", encoding="utf-8")
    (raw_dir / artifact.name).write_text("OCR 文本", encoding="utf-8")

    (kb_dir / "manifest.json").write_text(
        json.dumps(
            {
                "kb_name": "interview_bank",
                "created_at": "2026-05-12T00:00:00+08:00",
                "total_files": 1,
                "files": [
                    {
                        "file_name": source_pdf.name,
                        "relative_path": "data/knowledge_bases/interview_bank/raw/示范作答.pdf",
                        "estimated_content_type": "示范表达",
                        "estimated_question_type": "综合分析",
                        "estimated_position": "综合管理",
                        "estimated_difficulty": "medium",
                        "size": source_pdf.stat().st_size,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "ocr_manifest.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "source_pdf": str(source_pdf),
                        "artifact": str(artifact),
                        "start": 0,
                        "end": 1,
                        "page_range": "p0-1",
                        "engine": "mineru",
                        "lang": "ch",
                        "device": "cpu",
                        "formula": False,
                        "table": False,
                        "created_at": "2026-05-12T00:00:00+08:00",
                        "ok": True,
                        "chars": 6,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (kb_dir / "metadata.json").write_text(
        json.dumps({"file_hashes": {artifact.name: "hash"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest_path = ocr.sync_ocr_manifest_to_kb_manifest(
        kb_name="interview_bank",
        base_dir=base_dir,
        output_dir=output_dir,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["total_files"] == 2
    assert manifest["source_counts"] == {"original_raw": 1, "derived_ocr": 1}
    assert manifest["ocr"]["total_records"] == 1
    assert manifest["ocr"]["indexed_records"] == 1

    derived = [item for item in manifest["files"] if item["source_kind"] == "derived_ocr"]
    assert len(derived) == 1
    assert derived[0]["file_name"] == artifact.name
    assert derived[0]["derived_from"] == source_pdf.name
    assert derived[0]["estimated_content_type"] == "示范表达"
    assert derived[0]["estimated_question_type"] == "综合分析"
    assert derived[0]["ocr_quality_status"] == "usable"
    assert derived[0]["ingestion_status"] == "indexed"
    assert derived[0]["indexed"] is True
    assert derived[0]["derivation"]["engine"] == "mineru"
    assert derived[0]["derivation"]["page_range"] == "p0-1"

    ocr.sync_ocr_manifest_to_kb_manifest(
        kb_name="interview_bank",
        base_dir=base_dir,
        output_dir=output_dir,
    )
    manifest_again = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len([item for item in manifest_again["files"] if item["source_kind"] == "derived_ocr"]) == 1
