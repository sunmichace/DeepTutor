"""LLM-based tag backfill for interview_bank manifest.

Purpose
-------
The rule-based enrichment (``scripts/enrich_manifest_tags.py``) covers ~80%
of files cleanly. The remaining "suspicious" rows — generic 综合课程 /
综合套题 / 经验笔记 categories, or files the rules can't disambiguate —
need a second pass. This script uses DeepSeek to refine those long-tail
tags, cached to ``data/cache/llm/`` so repeated dry-runs cost nothing.

Safety contract
---------------
- Default mode is ``--dry-run``. ``--commit`` is required to mutate the
  manifest. Even ``--commit`` only writes back files that previously had
  a sentinel (empty / default) value — strong tags set by rules or a
  previous LLM pass are never overwritten without ``--overwrite``.
- Every prompt is cached by sha256(prompt + system + model + schema
  version), so the second run reuses fetched responses.
- ``--max-api-calls N`` caps the live API call count per invocation so
  a misconfigured run cannot burn the whole quota.
- Responses are validated by a Pydantic schema; invalid responses are
  logged and skipped, never merged.

Usage
-----
    # See what would be done without calling the API
    python scripts/llm_backfill_tags.py --dry-run

    # Fill cache only (cheap: hit cache for entries we already asked)
    python scripts/llm_backfill_tags.py --cache-only

    # Actually call DeepSeek, up to 20 live calls
    python scripts/llm_backfill_tags.py --commit --max-api-calls 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from deeptutor.services.llm.cache import LLMCache  # noqa: E402

_SCHEMA_VERSION = "v1"
_DEFAULT_MODEL = "deepseek-chat"

MANIFEST_PATH = Path("data/knowledge_bases/interview_bank/manifest.json")

_SENTINELS = {
    "estimated_question_type": {"", "综合课程", "综合套题", "经验笔记"},
    "estimated_position": {"", "通用", "综合管理"},
    "estimated_difficulty": {"", "medium"},
}

_SYSTEM_PROMPT = (
    "你是公考面试资料管理员。只能返回一个 JSON 对象，不要任何解释。"
    "根据文件名 / 目录路径 / 已有标签推断题型、岗位、难度；"
    "每个字段都只能取给定候选之一，且 confidence 取 0-1 小数。"
)

_CANDIDATE_QUESTION_TYPES = [
    "母题", "真题", "示范作答", "练习", "亮点合集",
    "社会现象", "名言警句", "态度观点", "演讲发言", "漫画",
    "特殊问法", "现实问题", "情景模拟", "人际关系", "应急应变",
    "组织管理", "调查研究", "启示做法", "领导讲话", "论证素材",
    "热点", "复盘", "基础", "综合课程", "综合套题", "经验笔记",
]
_CANDIDATE_POSITIONS = [
    "公务员", "省考", "广东选调", "广东事业单位", "广东省考",
    "综合管理",
]
_CANDIDATE_DIFFICULTIES = ["easy", "medium", "hard"]


class TagSuggestion(BaseModel):
    """Structured LLM response schema."""

    question_type: str = Field(default="", max_length=32)
    position: str = Field(default="", max_length=32)
    difficulty: str = Field(default="", max_length=16)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=160)


@dataclass
class BackfillStats:
    total: int = 0
    skipped_clean: int = 0
    suspicious: int = 0
    cache_hits: int = 0
    api_calls: int = 0
    invalid_responses: int = 0
    updates: int = 0
    reached_limit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _is_sentinel(field: str, value: object) -> bool:
    text = "" if value is None else str(value).strip()
    return text in _SENTINELS.get(field, {""})


def _needs_backfill(entry: dict[str, Any]) -> bool:
    return any(
        _is_sentinel(field, entry.get(field)) for field in _SENTINELS
    )


def _build_prompt(entry: dict[str, Any]) -> str:
    lines = [
        f"文件名: {entry.get('file_name', '?')}",
        f"路径: {entry.get('relative_path', '?')}",
        f"来源: {entry.get('source_kind', '?')}",
        f"现有题型: {entry.get('estimated_question_type') or '(空)'}",
        f"现有岗位: {entry.get('estimated_position') or '(空)'}",
        f"现有难度: {entry.get('estimated_difficulty') or '(默认)'}",
        "",
        "候选题型: " + "、".join(_CANDIDATE_QUESTION_TYPES),
        "候选岗位: " + "、".join(_CANDIDATE_POSITIONS),
        "候选难度: " + "、".join(_CANDIDATE_DIFFICULTIES),
        "",
        "返回 JSON 对象，字段：question_type, position, difficulty, confidence, reason。",
        "confidence < 0.6 的字段请返回空字符串。",
    ]
    return "\n".join(lines)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_response(raw: str) -> TagSuggestion | None:
    match = _JSON_RE.search(raw or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return TagSuggestion.model_validate(data)
    except ValidationError:
        return None


def _apply_suggestion(
    entry: dict[str, Any],
    suggestion: TagSuggestion,
    *,
    overwrite: bool,
) -> list[str]:
    """Merge validated suggestion back into the manifest entry."""
    applied: list[str] = []
    mapping = {
        "estimated_question_type": suggestion.question_type,
        "estimated_position": suggestion.position,
        "estimated_difficulty": suggestion.difficulty,
    }
    candidates = {
        "estimated_question_type": _CANDIDATE_QUESTION_TYPES,
        "estimated_position": _CANDIDATE_POSITIONS,
        "estimated_difficulty": _CANDIDATE_DIFFICULTIES,
    }
    for field, value in mapping.items():
        clean = (value or "").strip()
        if not clean or clean not in candidates[field]:
            continue
        if not overwrite and not _is_sentinel(field, entry.get(field)):
            continue
        if entry.get(field) == clean:
            continue
        entry[field] = clean
        applied.append(field)
    if applied:
        entry.setdefault("_llm_backfill", {})[_SCHEMA_VERSION] = {
            "confidence": suggestion.confidence,
            "reason": suggestion.reason[:160],
            "applied": applied,
        }
    return applied


async def _run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    stats = BackfillStats(total=len(files))
    cache = LLMCache(root=Path(args.cache_dir))

    # Lazily import the live LLM client only when we might call it,
    # keeping dry-run free of provider config requirements.
    live_complete = None
    if args.commit or args.cache_only:
        try:
            from deeptutor.services.llm import complete as _complete

            live_complete = _complete
        except Exception as exc:  # pragma: no cover — provider config error
            print(f"live LLM client unavailable: {exc}", file=sys.stderr)
            if args.commit:
                return 2

    for entry in files:
        if not _needs_backfill(entry):
            stats.skipped_clean += 1
            continue
        stats.suspicious += 1

        prompt = _build_prompt(entry)
        extra_key = _SCHEMA_VERSION

        cached = cache.get(
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            model=args.model,
            extra=extra_key,
        )
        response: str | None
        if cached is not None:
            stats.cache_hits += 1
            response = cached
        elif args.dry_run:
            response = None
        else:
            if args.max_api_calls is not None and stats.api_calls >= args.max_api_calls:
                stats.reached_limit = True
                break
            if live_complete is None:
                stats.reached_limit = True
                break
            stats.api_calls += 1
            try:
                response = await live_complete(
                    prompt=prompt,
                    system_prompt=_SYSTEM_PROMPT,
                    model=args.model,
                )
            except Exception as exc:  # pragma: no cover — provider error
                print(f"LLM call failed for {entry.get('file_name')}: {exc}", file=sys.stderr)
                response = None
            else:
                cache.set(
                    prompt=prompt,
                    system_prompt=_SYSTEM_PROMPT,
                    model=args.model,
                    extra=extra_key,
                    response=response,
                )

        if response is None:
            continue
        suggestion = _parse_response(response)
        if suggestion is None:
            stats.invalid_responses += 1
            continue
        if args.commit:
            applied = _apply_suggestion(entry, suggestion, overwrite=args.overwrite)
            if applied:
                stats.updates += 1
        else:
            # Dry-run: count what would change but don't mutate.
            preview = dict(entry)
            applied = _apply_suggestion(preview, suggestion, overwrite=args.overwrite)
            if applied:
                stats.updates += 1

    if args.commit and stats.updates:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"manifest updated: {manifest_path}")

    print("=== backfill stats ===")
    for k, v in stats.to_dict().items():
        print(f"  {k}: {v}")
    if not args.commit:
        print("dry-run: no changes written (pass --commit to persist).")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--cache-dir", default="data/cache/llm")
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(default) inspect cache, never call live LLM, never write manifest.",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Allow LLM calls for uncached entries, but do not write manifest.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Call LLM for uncached entries AND persist merged tags to manifest.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace even non-sentinel tags. Only use for known-bad fields.",
    )
    parser.add_argument(
        "--max-api-calls",
        type=int,
        default=20,
        help="Hard cap on live LLM calls per run (default 20; set 0 to disable live).",
    )
    args = parser.parse_args(argv)

    if args.commit:
        args.dry_run = False
    if args.cache_only:
        args.dry_run = False
    if args.max_api_calls is not None and args.max_api_calls <= 0:
        args.max_api_calls = 0
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
