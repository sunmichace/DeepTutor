"""Rule-based enrichment of interview_bank manifest tags.

Reads data/knowledge_bases/interview_bank/manifest.json and fills in
estimated_question_type / estimated_position / estimated_difficulty
based on filename and directory patterns.

Usage:
    python scripts/enrich_manifest_tags.py           # write back
    python scripts/enrich_manifest_tags.py --dry-run # preview only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

MANIFEST_PATH = Path("data/knowledge_bases/interview_bank/manifest.json")

QUESTION_TYPE_RULES: list[tuple[str, str]] = [
    ("领导讲话", "领导讲话"),
    ("社会现象", "社会现象"),
    ("名言警句", "名言警句"),
    ("态度观点", "态度观点"),
    ("观点理解", "态度观点"),
    ("演讲发言", "演讲发言"),
    ("漫画", "漫画"),
    ("特殊问法", "特殊问法"),
    ("现实问题", "现实问题"),
    ("情景模拟", "情景模拟"),
    ("人际关系", "人际关系"),
    ("应急应变", "应急应变"),
    ("应急处置", "应急应变"),
    ("组织管理", "组织管理"),
    ("计划组织", "组织管理"),
    ("调查研究", "调查研究"),
    ("启示做法", "启示做法"),
    ("示范作答", "示范作答"),
    ("示范答题", "示范作答"),
    ("论证素材", "论证素材"),
    ("论证逻辑", "论证素材"),
    ("热点押题", "热点"),
    ("热门考点", "热点"),
    ("母题", "母题"),
    ("亮点合集", "亮点合集"),
    ("复盘记录", "复盘"),
    ("真题", "真题"),
    ("试题", "真题"),
    ("练习题", "练习"),
    ("课程练习", "练习"),
    ("必背模块", "基础"),
    ("高分", "经验笔记"),
    ("前辈", "经验笔记"),
    ("学员笔记", "经验笔记"),
    ("第1套", "综合套题"),
    ("第2套", "综合套题"),
    ("第3套", "综合套题"),
    ("第4套", "综合套题"),
    ("说公务员面试", "综合课程"),
]

POSITION_RULES: list[tuple[str, str]] = [
    ("广东选调", "广东选调"),
    ("广东事业", "广东事业单位"),
    ("广东A177", "广东省考"),
    ("25省考", "省考"),
    ("山东省情", "省考"),
    ("公务员面试", "公务员"),
    ("老夏", "公务员"),
    ("面试相关", "公务员"),
    ("及第街", "公务员"),
    ("结构化面试", "公务员"),
    ("面试真题", "公务员"),
    ("复盘记录", "公务员"),
]

DIFFICULTY_RULES: list[tuple[str, str]] = [
    ("必背模块", "easy"),
    ("（必背）", "easy"),
    ("母题", "easy"),
    ("第1节", "easy"),
    ("01、论证逻辑", "easy"),
    ("高分", "hard"),
    ("前辈笔记", "hard"),
    ("热门考点", "hard"),
    ("热点押题", "hard"),
    ("200页", "hard"),
    ("200例", "hard"),
    ("100题", "hard"),
    ("100页", "hard"),
    ("50例", "medium"),
    ("真题", "medium"),
    ("试题", "medium"),
    ("示范作答", "medium"),
    ("典型真题", "medium"),
    ("复盘记录", "medium"),
    ("练习", "medium"),
]


def match_first(haystack: str, rules: list[tuple[str, str]]) -> str | None:
    for needle, tag in rules:
        if needle in haystack:
            return tag
    return None


def derive_tags(file_entry: dict) -> dict:
    name = file_entry.get("file_name", "")
    rel = file_entry.get("relative_path", "")
    haystack = f"{rel}|{name}"

    out = {}
    if qt := match_first(haystack, QUESTION_TYPE_RULES):
        out["estimated_question_type"] = qt
    if pos := match_first(haystack, POSITION_RULES):
        out["estimated_position"] = pos
    if diff := match_first(haystack, DIFFICULTY_RULES):
        out["estimated_difficulty"] = diff
    return out


_OCR_NAME_RE = re.compile(r"^(?P<stem>.+?)__ocr_p\d+(?:-\d+)?\.md$")

_INHERITABLE_FIELDS = (
    "estimated_question_type",
    "estimated_position",
    "estimated_difficulty",
    "estimated_content_type",
)


def _is_default_value(field: str, value: object) -> bool:
    sentinels = DEFAULT_SENTINELS_FOR_INHERIT.get(field, {""})
    if value is None:
        return True
    text = str(value).strip()
    return text in sentinels


DEFAULT_SENTINELS_FOR_INHERIT = {
    "estimated_question_type": {""},
    "estimated_position": {"", "通用"},
    "estimated_difficulty": {"", "medium"},
    "estimated_content_type": {""},
}


def _inherit_ocr_from_source(files: list[dict]) -> int:
    """Backfill derived_ocr files with their source PDF's tags.

    Each ``__ocr_pX-Y.md`` is matched to a ``<stem>.{pdf,docx,doc}``
    entry; whenever the OCR row's tag is empty / default and the
    parent has a stronger value, the parent's value is copied over.
    Returns the number of fields updated.
    """
    by_stem: dict[str, dict] = {}
    for entry in files:
        if entry.get("source_kind") != "original_raw":
            continue
        name = str(entry.get("file_name") or "")
        if "." not in name:
            continue
        stem = name.rsplit(".", 1)[0]
        # Don't override if multiple raw files share the same stem.
        by_stem.setdefault(stem, entry)

    changed = 0
    for entry in files:
        if entry.get("source_kind") != "derived_ocr":
            continue
        name = str(entry.get("file_name") or "")
        match = _OCR_NAME_RE.match(name)
        if not match:
            continue
        parent = by_stem.get(match.group("stem"))
        if not parent:
            continue
        for field in _INHERITABLE_FIELDS:
            parent_val = parent.get(field)
            if _is_default_value(field, parent_val):
                continue
            child_val = entry.get(field)
            if _is_default_value(field, child_val) and child_val != parent_val:
                entry[field] = parent_val
                changed += 1
    return changed


def report(files: list[dict], label: str) -> None:
    qt = Counter(f.get("estimated_question_type") or "<empty>" for f in files)
    pos = Counter(f.get("estimated_position") or "<empty>" for f in files)
    diff = Counter(f.get("estimated_difficulty") or "<empty>" for f in files)
    print(f"\n=== {label} (total {len(files)}) ===")
    print("question_type:", dict(qt))
    print("position:     ", dict(pos))
    print("difficulty:   ", dict(diff))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    args = parser.parse_args()

    path = Path(args.manifest)
    if not path.exists():
        print(f"manifest not found: {path}", file=sys.stderr)
        return 1

    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    report(files, "BEFORE")

    changed = 0
    for f in files:
        new_tags = derive_tags(f)
        for k, v in new_tags.items():
            old = f.get(k)
            if old == v:
                continue
            # only overwrite empty or default sentinel values
            if old and old not in ("", "通用", "medium", "综合管理"):
                continue
            f[k] = v
            changed += 1
        # question_type has no default sentinel—overwrite empty only
        if "estimated_question_type" in new_tags:
            pass  # already handled above

    inherited = _inherit_ocr_from_source(files)
    changed += inherited

    report(files, "AFTER")
    print(f"\nfield updates applied: {changed} (ocr inherited: {inherited})")

    if args.dry_run:
        print("dry-run: manifest not written")
        return 0

    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"manifest updated: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
