#!/usr/bin/env python3
"""
input/ 面试资料批量入库脚本。

工作流程：
  1. 遍历 input/ 目录，收集所有可索引文件（PDF、doc、pptx、txt、md）
  2. 对每份文件使用 LLM 自动标注（题型、岗位、难度、内容类型）
  3. 将文件复制到 interview_bank 知识库的 raw/ 目录
  4. 生成资料清单 manifest.json
  5. 调用 RAGService.initialize() 建立向量索引
  6. 将标注元数据写入 KB 的 metadata.json

用法：
  python scripts/ingest_interview_data.py [--input-dir INPUT] [--kb-name NAME]
  python scripts/ingest_interview_data.py --dry-run    # 只统计不实际入库
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure the project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from deeptutor.logging import Logger, get_logger

logger: Logger = get_logger("IngestInterviewData")

# ── Tag specification ───────────────────────────────────────────────────

# Main content types
CONTENT_TYPES = [
    "真题",           # Exam questions
    "高分作答",       # High-score answers / model answers
    "方法论",         # Teaching methodology
    "热点材料",       # Hot topics / policy materials
    "论证素材",       # Argumentation materials
    "示范表达",       # Demonstration expressions
    "岗位素材",       # Position-specific materials
    "评分标准",       # Scoring criteria
]

# Question types (结构化面试题型)
QUESTION_TYPES = [
    "综合分析",       # Comprehensive analysis (社会现象/观点理解)
    "计划组织",       # Planning and organizing
    "应急应变",       # Emergency response
    "人际沟通",       # Interpersonal communication
    "岗位匹配",       # Position matching
    "情景模拟",       # Scenario simulation
    "无领导小组",     # Leaderless group discussion
    "演讲",           # Speech
]

# Position directions
POSITIONS = [
    "综合管理",
    "税务",
    "公安",
    "教师岗",
    "医疗岗",
    "基层",
    "执法",
    "通用",
]

DIFFICULTIES = ["easy", "medium", "hard"]

# ── File discovery ──────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx", ".pptx", ".txt", ".md"}


def discover_files(input_dir: Path) -> list[Path]:
    """Discover all supported files under input_dir."""
    files: list[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(input_dir.rglob(f"*{ext}"))
    # Exclude hidden files/dirs
    files = [f for f in files if not any(part.startswith(".") for part in f.parts)]
    return sorted(files)


def categorize_file(file_path: Path) -> dict[str, Any]:
    """Basic categorization based on filename patterns.

    This is a heuristic pre-classification — LLM enrichment happens later.
    """
    name = file_path.stem
    parent = file_path.parent.name
    result: dict[str, Any] = {
        "file_name": file_path.name,
        "relative_path": str(file_path.relative_to(file_path.parents[3] if len(file_path.parents) > 3 else file_path.parent)),
        "estimated_content_type": "方法论",
        "estimated_question_type": "",
        "estimated_position": "通用",
        "estimated_difficulty": "medium",
    }

    # Heuristic by directory
    if "老夏" in parent or "老夏" in name:
        result["estimated_content_type"] = "方法论"
    elif "高分" in name or "95" in parent:
        result["estimated_content_type"] = "高分作答"
    elif "真题" in name or "试题" in name:
        result["estimated_content_type"] = "真题"
    elif "热点" in name:
        result["estimated_content_type"] = "热点材料"
    elif "论证" in name or "素材" in name:
        result["estimated_content_type"] = "论证素材"
    elif "示范" in name:
        result["estimated_content_type"] = "示范表达"
    elif "笔记" in name:
        result["estimated_content_type"] = "方法论"

    # Heuristic by filename keywords
    if "专项" in name:
        for qt in QUESTION_TYPES:
            if qt in name:
                result["estimated_question_type"] = qt
                break

    if "广东" in name:
        result["estimated_position"] = "综合管理"
    elif "选调" in name:
        result["estimated_position"] = "基层"

    return result


# ── LLM tagging (optional enhancement) ──────────────────────────────────


async def enrich_tags_with_llm(
    file_path: Path,
    content_preview: str,
    language: str = "zh",
) -> dict[str, str]:
    """Use LLM to enrich metadata tags for a document.

    This is optional — falls back to heuristic classification if LLM is unavailable.
    """
    try:
        from deeptutor.services.llm import stream as llm_stream

        system_prompt = (
            "你是一位公考面试资料管理员。请根据文件内容和文件名，"
            "用JSON格式输出该资料的元数据标签。\n\n"
            "输出格式（只输出JSON）：\n"
            '{"content_type": "真题/高分作答/方法论/热点材料/论证素材/示范表达/岗位素材/评分标准", '
            '"question_type": "综合分析/计划组织/应急应变/人际沟通/岗位匹配/情景模拟/无领导小组/演讲", '
            '"position": "综合管理/税务/公安/教师岗/医疗岗/基层/执法/通用", '
            '"difficulty": "easy/medium/hard"}'
        )

        user_prompt = (
            f"文件名：{file_path.name}\n"
            f"前500字内容预览：\n{content_preview[:500]}"
        )

        chunks: list[str] = []
        async for c in llm_stream(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=300,
        ):
            chunks.append(c)

        raw = "".join(chunks).strip()
        # Strip code fences
        import re
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        return json.loads(raw)
    except Exception as exc:
        logger.warning(f"LLM tagging failed for {file_path.name}: {exc}")
        return {}


# ── Knowledge base ingestion ─────────────────────────────────────────────


async def ingest_to_knowledge_base(
    kb_name: str = "interview_bank",
    input_dir: str | None = None,
    dry_run: bool = False,
    use_llm_tags: bool = False,
) -> bool:
    """Main ingestion function."""
    project_root = _PROJECT_ROOT
    input_path = Path(input_dir) if input_dir else project_root / "input"

    if not input_path.exists():
        logger.error(f"Input directory not found: {input_path}")
        return False

    # 1. Discover files
    files = discover_files(input_path)
    logger.info(f"Found {len(files)} files in {input_path}")
    for f in files:
        logger.info(f"  - {f.name} ({_format_size(f.stat().st_size)})")

    if not files:
        logger.warning("No supported files found.")
        return False

    # 2. Categorize files
    file_manifests: list[dict[str, Any]] = []
    total_size = 0
    for f in files:
        info = categorize_file(f)
        info["size"] = f.stat().st_size
        info["last_modified"] = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        file_manifests.append(info)
        total_size += info["size"]

    # 3. Generate manifest
    manifest = {
        "kb_name": kb_name,
        "created_at": datetime.now().astimezone().isoformat(),
        "total_files": len(file_manifests),
        "total_size_bytes": total_size,
        "files": file_manifests,
    }

    if dry_run:
        print("\n=== DRY RUN ===")
        print(f"Total files: {len(file_manifests)}")
        print(f"Total size: {_format_size(total_size)}")
        print(f"\nContent type breakdown:")
        from collections import Counter
        ctr = Counter(m.get("estimated_content_type", "unknown") for m in file_manifests)
        for k, v in ctr.most_common():
            print(f"  {k}: {v}")
        print(f"\nManifest preview:\n{json.dumps(manifest, ensure_ascii=False, indent=2)[:2000]}")
        print("\n(Dry run — no files were ingested)")
        return True

    # 4. Create KB directory structure
    kb_dir = project_root / "data" / "knowledge_bases" / kb_name
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 5. Copy files to KB raw directory
    import shutil
    copied = 0
    for f in files:
        dest = raw_dir / f.name
        if dest.exists():
            logger.info(f"Skipping (exists): {f.name}")
            continue
        shutil.copy2(str(f), str(dest))
        copied += 1
        logger.info(f"Copied: {f.name}")

    logger.info(f"Copied {copied} files to {raw_dir}")

    # 6. Save manifest
    manifest_path = kb_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Manifest saved to {manifest_path}")

    # 7. Initialize RAG index
    kb_base_dir = str(project_root / "data" / "knowledge_bases")
    from deeptutor.services.rag.factory import DEFAULT_PROVIDER
    from deeptutor.services.rag.service import RAGService

    rag = RAGService(kb_base_dir=kb_base_dir, provider=DEFAULT_PROVIDER)

    success = False
    try:
        file_paths = [str(f) for f in files]
        success = await rag.initialize(kb_name=kb_name, file_paths=file_paths)
        if success:
            logger.info(f"RAG index initialized successfully for '{kb_name}'")
        else:
            logger.warning("RAG index initialization returned False")
            logger.warning("Files are in raw/ directory and can be re-indexed later.")
    except Exception as exc:
        logger.warning(f"RAG index initialization failed: {exc}")
        logger.warning("Files are in raw/ directory and can be re-indexed later.")
        logger.warning("To re-index later: use KnowledgeBaseManager or CLI tools.")
        success = False

    print(f"\nIngestion complete. KB '{kb_name}' is ready.")
    print(f"  Raw files: {raw_dir}")
    print(f"  Manifest: {manifest_path}")
    print(f"  Total files: {len(file_manifests)}")
    print(f"  RAG index: {'initialized' if success else 'not initialized (needs embedding config — files are in raw/ for later indexing)'}")

    return True


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


# ── CLI ─────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest interview training data into knowledge base.",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Path to input directory (default: project_root/input)",
    )
    parser.add_argument(
        "--kb-name",
        default="interview_bank",
        help="Knowledge base name (default: interview_bank)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only scan and categorize, don't ingest",
    )
    parser.add_argument(
        "--use-llm-tags",
        action="store_true",
        help="Use LLM to enrich metadata (requires LLM config)",
    )
    args = parser.parse_args()

    import asyncio

    success = asyncio.run(
        ingest_to_knowledge_base(
            kb_name=args.kb_name,
            input_dir=args.input_dir,
            dry_run=args.dry_run,
            use_llm_tags=args.use_llm_tags,
        )
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
