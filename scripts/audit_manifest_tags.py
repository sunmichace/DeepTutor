"""Audit interview_bank manifest tags: coverage, defaults, sampling for review.

Outputs coverage counts and a stratified sample to ``tag_audit_report.json``
so the result can be reviewed in a diff or fed into manual spot-check.

Usage:
    python scripts/audit_manifest_tags.py
    python scripts/audit_manifest_tags.py --sample-per-bucket 3
    python scripts/audit_manifest_tags.py --output /tmp/audit.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

MANIFEST_PATH = Path("data/knowledge_bases/interview_bank/manifest.json")
DEFAULT_OUTPUT = Path("data/knowledge_bases/interview_bank/tag_audit_report.json")
DEFAULT_REVIEW_OUTPUT = Path("data/knowledge_bases/interview_bank/tag_audit_review.md")

DEFAULT_SENTINELS = {
    "estimated_question_type": {"", None},
    "estimated_position": {"", None, "通用"},
    "estimated_difficulty": {"", None, "medium"},
    "estimated_content_type": {"", None},
}


def _bucket_key(value: object) -> str:
    if value is None:
        return "<null>"
    text = str(value).strip()
    return text or "<empty>"


def _coverage(files: list[dict], field: str) -> dict:
    values = [f.get(field) for f in files]
    counts = Counter(_bucket_key(v) for v in values)
    sentinels = DEFAULT_SENTINELS.get(field, {""})
    non_default = sum(
        1 for v in values if v not in sentinels and _bucket_key(v) not in {"<empty>", "<null>"}
    )
    return {
        "field": field,
        "total": len(values),
        "non_default": non_default,
        "non_default_ratio": round(non_default / max(len(values), 1), 3),
        "distribution": dict(counts.most_common()),
    }


def _stratified_sample(
    files: list[dict],
    *,
    field: str,
    per_bucket: int,
    rng: random.Random,
) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for f in files:
        buckets[_bucket_key(f.get(field))].append(f)
    sample: list[dict] = []
    for key, bucket in sorted(buckets.items()):
        picks = rng.sample(bucket, min(per_bucket, len(bucket)))
        for item in picks:
            sample.append(
                {
                    "audit_field": field,
                    "bucket": key,
                    "file_name": item.get("file_name"),
                    "relative_path": item.get("relative_path"),
                    "source_kind": item.get("source_kind"),
                    "estimated_question_type": item.get("estimated_question_type"),
                    "estimated_position": item.get("estimated_position"),
                    "estimated_difficulty": item.get("estimated_difficulty"),
                }
            )
    return sample


def _suspicious_rows(files: list[dict]) -> list[dict]:
    """Entries likely to be low-confidence tags — reviewer should prioritise these."""
    suspicious: list[dict] = []
    for f in files:
        reasons: list[str] = []
        qt = f.get("estimated_question_type") or ""
        pos = f.get("estimated_position") or ""
        diff = f.get("estimated_difficulty") or ""
        name = f.get("file_name") or ""
        rel = f.get("relative_path") or ""

        if qt in {"综合课程", "综合套题", "经验笔记"}:
            reasons.append(f"generic question_type={qt}")
        if pos == "通用":
            reasons.append("position is default 通用")
        if diff == "medium" and ("高分" in name or "200" in name or "100" in name):
            reasons.append("difficulty=medium but filename hints hard")
        if qt == "" or qt is None:
            reasons.append("question_type missing")
        if f.get("source_kind") == "derived_ocr" and not qt:
            reasons.append("OCR derived without question_type")
        if reasons:
            suspicious.append(
                {
                    "file_name": name,
                    "relative_path": rel,
                    "source_kind": f.get("source_kind"),
                    "estimated_question_type": qt,
                    "estimated_position": pos,
                    "estimated_difficulty": diff,
                    "reasons": reasons,
                }
            )
    return suspicious


def _build_review_sheet(
    files: list[dict],
    *,
    coverage: dict[str, dict],
    suspicious: list[dict],
    samples: dict[str, list[dict]],
) -> str:
    """Emit a Markdown checklist for manual tag review.

    The sheet is designed to be opened side-by-side with the source file
    and filled in (☐ → ☑ + short note) without touching the JSON report.
    """
    lines: list[str] = []
    lines.append("# interview_bank manifest tag review")
    lines.append("")
    lines.append(f"Total files: **{len(files)}**")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append("| field | non_default | ratio |")
    lines.append("| --- | --- | --- |")
    for field, info in coverage.items():
        lines.append(
            f"| `{field}` | {info['non_default']} / {info['total']} "
            f"| {info['non_default_ratio']} |"
        )
    lines.append("")

    lines.append("## How to use this sheet")
    lines.append("")
    lines.append(
        "Walk through each row below, open the referenced file, and mark the "
        "tag as correct (`☑`) or wrong (`☒`). For wrong rows, write the "
        "correct value in the notes column. After finishing, update "
        "`plan/2026-05-13-项目当前状态与下一步计划.md` with the误判率 "
        "(wrong / reviewed) so 2.2 has a concrete verdict."
    )
    lines.append("")

    for field_label, field_key in (
        ("Question type", "estimated_question_type"),
        ("Difficulty", "estimated_difficulty"),
        ("Position", "estimated_position"),
    ):
        lines.append(f"## {field_label} (`{field_key}`)")
        lines.append("")
        lines.append("| ☐ | file | bucket | note |")
        lines.append("| --- | --- | --- | --- |")
        for row in samples.get(field_key, []):
            file_name = row.get("file_name") or "?"
            bucket = row.get("bucket") or "?"
            lines.append(f"| ☐ | `{file_name}` | {bucket} | |")
        lines.append("")

    lines.append("## Suspicious rows")
    lines.append("")
    if not suspicious:
        lines.append("_None — all rows passed the rule-level sanity checks._")
    else:
        lines.append("| ☐ | file | reasons | note |")
        lines.append("| --- | --- | --- | --- |")
        for row in suspicious:
            reasons = "; ".join(row.get("reasons") or [])
            lines.append(f"| ☐ | `{row.get('file_name') or '?'}` | {reasons} | |")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--review-md",
        default=str(DEFAULT_REVIEW_OUTPUT),
        help="Path to write a human-reviewable Markdown checklist.",
    )
    parser.add_argument("--sample-per-bucket", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260513)
    args = parser.parse_args()

    path = Path(args.manifest)
    if not path.exists():
        print(f"manifest not found: {path}", file=sys.stderr)
        return 1

    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    rng = random.Random(args.seed)

    coverage = {
        field: _coverage(files, field)
        for field in DEFAULT_SENTINELS
    }

    samples = {
        field: _stratified_sample(
            files,
            field=field,
            per_bucket=args.sample_per_bucket,
            rng=rng,
        )
        for field in ("estimated_question_type", "estimated_difficulty", "estimated_position")
    }

    suspicious = _suspicious_rows(files)

    report = {
        "manifest": str(path),
        "total_files": len(files),
        "source_counts": Counter(f.get("source_kind") or "?" for f in files),
        "coverage": coverage,
        "suspicious_count": len(suspicious),
        "suspicious": suspicious,
        "stratified_samples": samples,
    }

    # Counter isn't JSON serialisable
    report["source_counts"] = dict(report["source_counts"])

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    review_path = Path(args.review_md) if args.review_md else None
    if review_path:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(
            _build_review_sheet(
                files,
                coverage=coverage,
                suspicious=suspicious,
                samples=samples,
            ),
            encoding="utf-8",
        )

    print("=== Coverage ===")
    for field, info in coverage.items():
        print(
            f"  {field}: non_default={info['non_default']}/{info['total']} "
            f"(ratio={info['non_default_ratio']})"
        )
    print(f"\n=== Suspicious rows: {len(suspicious)} ===")
    for row in suspicious[:10]:
        print(f"  - {row['file_name']}")
        for reason in row["reasons"]:
            print(f"      · {reason}")
    if len(suspicious) > 10:
        print(f"  ... {len(suspicious) - 10} more in report")

    print(f"\nReport written to {out}")
    if review_path:
        print(f"Review sheet written to {review_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
