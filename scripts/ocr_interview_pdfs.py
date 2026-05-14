#!/usr/bin/env python3
"""Generate OCR-derived Markdown for interview-bank PDFs.

This helper intentionally does not rebuild the vector index. It creates
reviewable Markdown artifacts that can be ingested later once the OCR quality is
accepted.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_BASE_DIR = _PROJECT_ROOT / "data" / "knowledge_bases"
_OCR_ENGINE = "mineru"


def _mineru_command() -> str:
    cmd = shutil.which("mineru")
    if not cmd:
        raise RuntimeError("MinerU CLI not found. Expected `mineru` on PATH.")
    return cmd


def _safe_stem(path: Path) -> str:
    stem = path.stem.strip().replace("/", "_").replace("\\", "_")
    return stem or "document"


def _range_suffix(start: int | None, end: int | None) -> str:
    if start is None and end is None:
        return "all"
    start_text = "0" if start is None else str(start)
    end_text = "end" if end is None else str(end)
    return f"p{start_text}-{end_text}"


def _find_markdown(output_root: Path, pdf: Path) -> Path:
    candidates = sorted(output_root.rglob(f"{pdf.stem}.md"))
    if not candidates:
        candidates = sorted(output_root.rglob("*.md"))
    if not candidates:
        raise RuntimeError(f"MinerU produced no Markdown under {output_root}")
    return candidates[0]


def run_ocr(
    *,
    pdf: Path,
    output_dir: Path,
    start: int | None,
    end: int | None,
    lang: str,
    device: str,
    keep_runs: bool,
    dry_run: bool,
) -> dict[str, Any]:
    """Run MinerU OCR for one PDF and copy the generated Markdown artifact."""
    if not pdf.exists():
        raise FileNotFoundError(f"PDF does not exist: {pdf}")
    if pdf.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file: {pdf}")

    mineru = _mineru_command()
    range_suffix = _range_suffix(start, end)
    artifact_name = f"{_safe_stem(pdf)}__ocr_{range_suffix}.md"
    artifact_path = output_dir / artifact_name
    mineru_root = output_dir / "_mineru_runs" / f"{_safe_stem(pdf)}__{range_suffix}"

    cmd = [
        mineru,
        "-p",
        str(pdf),
        "-o",
        str(mineru_root),
        "-m",
        "ocr",
        "-b",
        "pipeline",
        "-l",
        lang,
        "-d",
        device,
        "-f",
        "false",
        "-t",
        "false",
    ]
    if start is not None:
        cmd.extend(["-s", str(start)])
    if end is not None:
        cmd.extend(["-e", str(end)])

    result: dict[str, Any] = {
        "source_pdf": str(pdf),
        "artifact": str(artifact_path),
        "start": start,
        "end": end,
        "page_range": range_suffix,
        "engine": _OCR_ENGINE,
        "lang": lang,
        "device": device,
        "formula": False,
        "table": False,
        "command": cmd,
        "created_at": datetime.now().astimezone().isoformat(),
        "ok": False,
        "chars": 0,
        "quality_status": "pending",
    }

    if dry_run:
        result["dry_run"] = True
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    if mineru_root.exists():
        shutil.rmtree(mineru_root)

    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    result["returncode"] = proc.returncode
    if proc.returncode != 0:
        result["stdout"] = proc.stdout[-4000:]
        result["stderr"] = proc.stderr[-4000:]
        return result

    generated_md = _find_markdown(mineru_root, pdf)
    text = generated_md.read_text(encoding="utf-8")
    header = (
        f"<!-- OCR derived from: {pdf.name} -->\n"
        f"<!-- page_range: {range_suffix}; engine: mineru; lang: {lang}; "
        f"formula: false; table: false -->\n\n"
    )
    artifact_path.write_text(header + text, encoding="utf-8")
    if not keep_runs and mineru_root.exists():
        shutil.rmtree(mineru_root)
    result["ok"] = True
    result["chars"] = len(text.strip())
    result["quality_status"] = "usable" if result["chars"] else "empty"
    return result


def _load_existing_records(output_dir: Path) -> list[dict[str, Any]]:
    manifest_path = output_dir / "ocr_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    records = data.get("records", [])
    return records if isinstance(records, list) else []


def _merge_records(
    existing: list[dict[str, Any]],
    new_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in [*existing, *new_records]:
        if record.get("source_pdf") is not None:
            key = (
                str(record.get("source_pdf", "")),
                str(record.get("start", "")),
                str(record.get("end", "")),
            )
        else:
            key = ("artifact", str(record.get("artifact", "")), "")
        merged[key] = record
    return list(merged.values())


def _write_manifest(
    output_dir: Path,
    records: list[dict[str, Any]],
    *,
    append: bool = True,
) -> Path:
    manifest_path = output_dir / "ocr_manifest.json"
    all_records = _merge_records(_load_existing_records(output_dir), records) if append else records
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(),
        "total": len(all_records),
        "ok": sum(1 for item in all_records if item.get("ok")),
        "records": all_records,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _relative_to_project(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)


def _indexed_file_names(kb_dir: Path) -> set[str]:
    names: set[str] = set()
    metadata = _load_json(kb_dir / "metadata.json", {})
    file_hashes = metadata.get("file_hashes", {}) if isinstance(metadata, dict) else {}
    if isinstance(file_hashes, dict):
        names.update(str(name) for name in file_hashes)

    docstore = _load_json(kb_dir / "llamaindex_storage" / "docstore.json", {})
    docs = docstore.get("docstore/data", {}) if isinstance(docstore, dict) else {}
    if isinstance(docs, dict):
        for doc in docs.values():
            meta = doc.get("__data__", {}).get("metadata", {}) if isinstance(doc, dict) else {}
            file_name = meta.get("file_name") if isinstance(meta, dict) else None
            if file_name:
                names.add(str(file_name))
    return names


def _source_manifest_by_name(files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        if item.get("source_kind") == "derived_ocr":
            continue
        file_name = str(item.get("file_name") or "").strip()
        if file_name and file_name not in sources:
            sources[file_name] = item
    return sources


def _normalize_original_records(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        file_name = str(next_item.get("file_name") or "")
        if not next_item.get("source_kind"):
            next_item["source_kind"] = "derived_ocr" if "__ocr_" in file_name else "original_raw"
        normalized.append(next_item)
    return normalized


def _ocr_quality_status(record: dict[str, Any]) -> str:
    if not record.get("ok"):
        return "failed"
    explicit = str(record.get("quality_status") or "").strip()
    if explicit and explicit != "pending":
        return explicit
    return "usable" if int(record.get("chars") or 0) > 0 else "empty"


def _build_derived_manifest_record(
    *,
    record: dict[str, Any],
    kb_dir: Path,
    output_dir: Path,
    source_by_name: dict[str, dict[str, Any]],
    indexed_names: set[str],
) -> dict[str, Any]:
    artifact_value = str(record.get("artifact") or "").strip()
    artifact_path = Path(artifact_value)
    if not artifact_path.is_absolute():
        artifact_path = output_dir / artifact_path
    artifact_name = artifact_path.name
    raw_path = kb_dir / "raw" / artifact_name
    primary_path = raw_path if raw_path.exists() else artifact_path

    source_pdf = Path(str(record.get("source_pdf") or ""))
    source_name = source_pdf.name
    source = source_by_name.get(source_name, {})
    indexed = artifact_name in indexed_names
    if indexed:
        ingestion_status = "indexed"
    elif raw_path.exists():
        ingestion_status = "staged"
    elif record.get("ok"):
        ingestion_status = "generated"
    else:
        ingestion_status = "failed"

    stat_size = primary_path.stat().st_size if primary_path.exists() else 0
    last_modified = (
        datetime.fromtimestamp(primary_path.stat().st_mtime).astimezone().isoformat()
        if primary_path.exists()
        else str(record.get("created_at") or "")
    )
    page_start = record.get("start")
    page_end = record.get("end")
    page_range = str(record.get("page_range") or _range_suffix(page_start, page_end))

    return {
        "file_name": artifact_name,
        "relative_path": _relative_to_project(primary_path),
        "source_kind": "derived_ocr",
        "derived_from": source_name,
        "derived_from_path": source.get("relative_path") or str(record.get("source_pdf") or ""),
        "estimated_content_type": source.get("estimated_content_type") or "OCR文本",
        "estimated_question_type": source.get("estimated_question_type") or "",
        "estimated_position": source.get("estimated_position") or "通用",
        "estimated_difficulty": source.get("estimated_difficulty") or "medium",
        "size": stat_size,
        "last_modified": last_modified,
        "ocr_quality_status": _ocr_quality_status(record),
        "ingestion_status": ingestion_status,
        "indexed": indexed,
        "derivation": {
            "type": "ocr",
            "engine": record.get("engine") or _OCR_ENGINE,
            "source_pdf": str(record.get("source_pdf") or ""),
            "source_pdf_name": source_name,
            "page_start": page_start,
            "page_end": page_end,
            "page_range": page_range,
            "lang": record.get("lang") or "ch",
            "device": record.get("device") or "cpu",
            "formula": bool(record.get("formula", False)),
            "table": bool(record.get("table", False)),
            "chars": int(record.get("chars") or 0),
            "created_at": record.get("created_at") or "",
        },
    }


def sync_ocr_manifest_to_kb_manifest(
    *,
    kb_name: str,
    base_dir: Path = _DEFAULT_BASE_DIR,
    output_dir: Path | None = None,
) -> Path:
    """Merge OCR-derived artifacts into the KB's canonical manifest.json."""
    kb_dir = base_dir / kb_name
    manifest_path = kb_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"KB manifest not found: {manifest_path}")

    output_dir = output_dir or kb_dir / "ocr_text"
    ocr_manifest_path = output_dir / "ocr_manifest.json"
    ocr_manifest = _load_json(ocr_manifest_path, {})
    records = ocr_manifest.get("records", []) if isinstance(ocr_manifest, dict) else []
    if not isinstance(records, list):
        records = []

    manifest = _load_json(manifest_path, {})
    files = _normalize_original_records(manifest.get("files", []))
    source_by_name = _source_manifest_by_name(files)
    indexed_names = _indexed_file_names(kb_dir)

    derived = [
        _build_derived_manifest_record(
            record=record,
            kb_dir=kb_dir,
            output_dir=output_dir,
            source_by_name=source_by_name,
            indexed_names=indexed_names,
        )
        for record in records
        if isinstance(record, dict) and record.get("artifact")
    ]
    derived_by_name = {item["file_name"]: item for item in derived}
    kept = [
        item
        for item in files
        if str(item.get("file_name") or "") not in derived_by_name
    ]
    files = kept + sorted(derived_by_name.values(), key=lambda item: item["file_name"])

    counts = Counter(str(item.get("source_kind") or "original_raw") for item in files)
    manifest["schema_version"] = 2
    manifest["updated_at"] = datetime.now().astimezone().isoformat()
    manifest["total_files"] = len(files)
    manifest["total_size_bytes"] = sum(
        int(item.get("size") or 0)
        for item in files
        if isinstance(item, dict)
    )
    manifest["source_counts"] = {
        "original_raw": counts.get("original_raw", 0),
        "derived_ocr": counts.get("derived_ocr", 0),
    }
    manifest["ocr"] = {
        "manifest_path": _relative_to_project(ocr_manifest_path),
        "total_records": len(records),
        "ok_records": sum(1 for record in records if isinstance(record, dict) and record.get("ok")),
        "indexed_records": sum(1 for item in derived if item.get("indexed")),
    }
    manifest["files"] = files
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate OCR-derived Markdown artifacts for interview-bank PDFs.",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        default=[],
        help="PDF path. Can be provided multiple times.",
    )
    parser.add_argument("--kb-name", default="interview_bank")
    parser.add_argument("--base-dir", default=str(_DEFAULT_BASE_DIR))
    parser.add_argument("--start", type=int, default=None, help="Start page, 0-based.")
    parser.add_argument("--end", type=int, default=None, help="End page, 0-based.")
    parser.add_argument("--lang", default="ch")
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--keep-runs",
        action="store_true",
        help="Keep MinerU intermediate outputs under _mineru_runs for debugging.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. Defaults to data/knowledge_bases/<kb-name>/ocr_text.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--sync-kb-manifest",
        action="store_true",
        help="Merge ocr_manifest.json records into the KB manifest after OCR.",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Only merge an existing ocr_manifest.json into the KB manifest.",
    )
    args = parser.parse_args()

    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else _PROJECT_ROOT / "data" / "knowledge_bases" / args.kb_name / "ocr_text"
    )
    base_dir = Path(args.base_dir)

    if args.sync_only:
        manifest_path = sync_ocr_manifest_to_kb_manifest(
            kb_name=args.kb_name,
            base_dir=base_dir,
            output_dir=output_dir,
        )
        print(f"KB manifest synced: {manifest_path}")
        return 0

    if not args.pdf:
        parser.error("--pdf is required unless --sync-only is used")

    records = []
    for pdf_arg in args.pdf:
        record = run_ocr(
            pdf=Path(pdf_arg),
            output_dir=output_dir,
            start=args.start,
            end=args.end,
            lang=args.lang,
            device=args.device,
            keep_runs=args.keep_runs,
            dry_run=args.dry_run,
        )
        records.append(record)
        status = "OK" if record.get("ok") else "FAILED" if not args.dry_run else "DRY-RUN"
        print(f"{status}: {record['source_pdf']} -> {record['artifact']} ({record.get('chars', 0)} chars)")

    if not args.dry_run:
        manifest_path = _write_manifest(output_dir, records)
        print(f"Manifest: {manifest_path}")
        if args.sync_kb_manifest:
            kb_manifest_path = sync_ocr_manifest_to_kb_manifest(
                kb_name=args.kb_name,
                base_dir=base_dir,
                output_dir=output_dir,
            )
            print(f"KB manifest synced: {kb_manifest_path}")

    return 0 if all(item.get("ok") or args.dry_run for item in records) else 1


if __name__ == "__main__":
    sys.exit(main())
