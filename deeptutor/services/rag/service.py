"""Unified RAG service entry point."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from deeptutor.logging import get_logger

from .factory import (
    DEFAULT_PROVIDER,
    get_pipeline,
    has_pipeline,
    list_pipelines,
    normalize_provider_name,
)


class _RAGRawLogHandler(logging.Handler):
    def __init__(self, event_sink, loop) -> None:
        super().__init__(level=logging.DEBUG)
        self._event_sink = event_sink
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        if self._event_sink is None:
            return
        try:
            module_name = getattr(record, "module_name", record.name.split(".")[-1])
            level_name = getattr(record, "display_level", record.levelname)
            message = record.getMessage()
            line = f"[{module_name}] {level_name}: {message}".strip()
            if not line:
                return

            async def _emit() -> None:
                await self._event_sink(
                    "raw_log",
                    line,
                    {
                        "trace_layer": "raw",
                        "logger_name": record.name,
                        "log_level": level_name,
                        "module_name": module_name,
                    },
                )

            self._loop.create_task(_emit())
        except Exception:
            pass


DEFAULT_KB_BASE_DIR = str(
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge_bases"
)


class RAGService:
    """Unified RAG service that currently uses llamaindex provider(s)."""

    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self.logger = get_logger("RAGService")
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        from deeptutor.services.config import get_kb_config_service

        configured_default = (
            get_kb_config_service()
            .get_all_configs()
            .get("defaults", {})
            .get("rag_provider", DEFAULT_PROVIDER)
        )
        self.provider = normalize_provider_name(provider or configured_default)
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            self._pipeline = get_pipeline(self.provider, kb_base_dir=self.kb_base_dir)
        return self._pipeline

    async def initialize(
        self, kb_name: str, file_paths: List[str], **kwargs
    ) -> bool:
        self.logger.info(f"Initializing KB '{kb_name}' with provider '{self.provider}'")
        pipeline = self._get_pipeline()
        return await pipeline.initialize(
            kb_name=kb_name, file_paths=file_paths, **kwargs
        )

    async def search(
        self,
        query: str,
        kb_name: str,
        event_sink=None,
        **kwargs,
    ) -> Dict[str, Any]:
        kwargs.pop("mode", None)
        provider = self._get_provider_for_kb(kb_name)
        with self._capture_raw_logs(event_sink, provider):
            await self._emit_tool_event(
                event_sink,
                "status",
                f"Query: {query}",
                {"query": query, "kb_name": kb_name, "trace_layer": "summary"},
            )
            await self._emit_tool_event(
                event_sink,
                "status",
                f"Selecting provider: {provider}",
                {"provider": provider, "trace_layer": "summary"},
            )

            self.logger.info(
                f"Searching KB '{kb_name}' with provider '{provider}' and query: {query[:50]}..."
            )

            await self._emit_tool_event(
                event_sink,
                "status",
                f"Retrieving from knowledge base '{kb_name}'...",
                {"provider": provider, "trace_layer": "summary"},
            )

            try:
                pipeline = get_pipeline(provider, kb_base_dir=self.kb_base_dir)
                result = await pipeline.search(query=query, kb_name=kb_name, **kwargs)
            except Exception as exc:
                fallback = self._search_manifest_fallback(
                    query=query,
                    kb_name=kb_name,
                    limit=int(kwargs.get("limit", kwargs.get("top_k", 5)) or 5),
                    error=exc,
                )
                if fallback is None:
                    raise
                result = fallback

            if "query" not in result:
                result["query"] = query
            if "answer" not in result and "content" in result:
                result["answer"] = result["content"]
            if "content" not in result and "answer" in result:
                result["content"] = result["answer"]
            result["provider"] = normalize_provider_name(result.get("provider") or provider)

            answer = result.get("answer") or result.get("content") or ""
            await self._emit_tool_event(
                event_sink,
                "status",
                f"Retrieved {len(answer)} characters of grounded context.",
                {
                    "provider": result["provider"],
                    "kb_name": kb_name,
                    "trace_layer": "summary",
                },
            )

            return result

    def _search_manifest_fallback(
        self,
        *,
        query: str,
        kb_name: str,
        limit: int = 5,
        error: Exception | None = None,
    ) -> dict[str, Any] | None:
        """Return metadata-level matches when the vector index is unavailable."""
        manifest_path = Path(self.kb_base_dir) / kb_name / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest.get("files", [])
        except (json.JSONDecodeError, OSError) as manifest_exc:
            self.logger.warning(
                f"Could not read manifest fallback for KB '{kb_name}': {manifest_exc}"
            )
            return None

        if not isinstance(files, list) or not files:
            return None

        tokens = _tokenize_for_manifest_search(query)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            text = " ".join(
                str(item.get(key, ""))
                for key in (
                    "file_name",
                    "relative_path",
                    "estimated_content_type",
                    "estimated_question_type",
                    "estimated_position",
                    "estimated_difficulty",
                )
            )
            score = sum(1 for token in tokens if token and token in text)
            if score:
                ranked.append((score, item))

        if not ranked:
            ranked = [(0, item) for item in files if isinstance(item, dict)]

        ranked.sort(
            key=lambda pair: (
                pair[0],
                _manifest_content_priority(pair[1].get("estimated_content_type", "")),
                int(pair[1].get("size", 0) or 0),
            ),
            reverse=True,
        )
        selected = [item for _, item in ranked[:max(1, limit)]]
        lines = [
            "向量索引暂不可用，以下为知识库 manifest 元数据检索结果：",
        ]
        for idx, item in enumerate(selected, start=1):
            lines.append(
                (
                    f"{idx}. {item.get('file_name', '')} "
                    f"[{item.get('estimated_content_type', '未知')}; "
                    f"{item.get('estimated_question_type') or '通用题型'}; "
                    f"{item.get('estimated_position') or '通用岗位'}; "
                    f"{item.get('estimated_difficulty') or 'medium'}]"
                ).strip()
            )

        if error is not None:
            self.logger.warning(
                f"Vector RAG failed for KB '{kb_name}', using manifest fallback: {error}"
            )

        sources = [
            {
                "file_name": item.get("file_name", ""),
                "relative_path": item.get("relative_path", ""),
                "content_type": item.get("estimated_content_type", ""),
                "question_type": item.get("estimated_question_type", ""),
                "position": item.get("estimated_position", ""),
                "difficulty": item.get("estimated_difficulty", ""),
            }
            for item in selected
        ]
        answer = "\n".join(lines)
        return {
            "query": query,
            "answer": answer,
            "content": answer,
            "sources": sources,
            "provider": "manifest_fallback",
            "fallback": True,
            "fallback_reason": str(error) if error is not None else "vector index unavailable",
        }

    async def _emit_tool_event(
        self,
        event_sink,
        event_type: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        if event_sink is None:
            return
        await event_sink(event_type, message, metadata or {})

    def _capture_raw_logs(self, event_sink, provider: str):
        from contextlib import ExitStack, contextmanager
        import asyncio

        @contextmanager
        def _manager():
            if event_sink is None:
                yield
                return

            loop = asyncio.get_running_loop()
            handler = _RAGRawLogHandler(event_sink, loop)
            handler.setLevel(logging.DEBUG)
            targets = self._iter_rag_loggers(provider)
            with ExitStack() as stack:
                for logger in targets:
                    logger.addHandler(handler)
                    stack.callback(logger.removeHandler, handler)
                try:
                    yield
                finally:
                    handler.close()

        return _manager()

    def _iter_rag_loggers(self, provider: str) -> list[logging.Logger]:
        provider_name = normalize_provider_name(provider)
        names = {
            "deeptutor.RAGService",
            "deeptutor.RAGForward",
        }
        if provider_name == DEFAULT_PROVIDER:
            names.add("deeptutor.LlamaIndexPipeline")
        return [logging.getLogger(name) for name in sorted(names)]

    def _get_provider_for_kb(self, kb_name: str) -> str:
        """Resolve provider from KB config and normalize legacy values."""
        try:
            from deeptutor.services.config import get_kb_config_service

            service = get_kb_config_service()
            provider_raw = service.get_kb_config(kb_name).get("rag_provider")
            provider = normalize_provider_name(provider_raw)
            if provider_raw and provider_raw != provider:
                service.set_rag_provider(kb_name, provider)
                self.logger.info(
                    f"Normalized legacy provider '{provider_raw}' -> '{provider}' for KB '{kb_name}'"
                )
            return provider
        except Exception as e:
            self.logger.warning(f"Error reading provider from config: {e}, using instance provider")
            return self.provider

    async def delete(self, kb_name: str) -> bool:
        self.logger.info(f"Deleting KB '{kb_name}'")
        pipeline = self._get_pipeline()

        if hasattr(pipeline, "delete"):
            return await pipeline.delete(kb_name=kb_name)

        kb_dir = Path(self.kb_base_dir) / kb_name
        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info(f"Deleted KB directory: {kb_dir}")
            return True
        return False

    async def smart_retrieve(
        self,
        context: str,
        kb_name: str,
        query_hints: Optional[List[str]] = None,
        max_queries: int = 3,
    ) -> Dict[str, Any]:
        import asyncio

        queries = query_hints if query_hints else await self._generate_queries(context, max_queries)

        tasks = [self.search(query=q, kb_name=kb_name) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        passages: list[str] = []
        all_sources: list[dict] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            content = r.get("content") or r.get("answer") or ""
            if content:
                passages.append(content)
                all_sources.append({"query": r.get("query", ""), "provider": r.get("provider", "")})

        if not passages:
            return {"answer": "", "sources": []}

        aggregated = await self._aggregate(context, passages)
        return {"answer": aggregated, "sources": all_sources}

    async def _generate_queries(self, context: str, n: int) -> list[str]:
        try:
            from deeptutor.services.llm import complete

            prompt = (
                f"Generate {n} diverse search queries to retrieve information relevant "
                f"to the following context. Return ONLY the queries, one per line.\n\n"
                f"Context:\n{context[:2000]}"
            )
            raw = await complete(prompt, system_prompt="You are a search query generator.")
            lines = [l.strip().lstrip("0123456789.-) ") for l in raw.strip().split("\n") if l.strip()]
            return lines[:n] if lines else [context[:200]]
        except Exception:
            return [context[:200]]

    async def _aggregate(self, context: str, passages: list[str]) -> str:
        try:
            from deeptutor.services.llm import complete

            combined = "\n---\n".join(passages)
            prompt = (
                "Synthesise the following retrieved passages into a concise, "
                "relevant summary for the given context.\n\n"
                f"Context:\n{context[:1000]}\n\n"
                f"Passages:\n{combined[:6000]}"
            )
            return await complete(prompt, system_prompt="You are a knowledge synthesiser.")
        except Exception:
            return "\n\n".join(passages)

    @staticmethod
    def list_providers() -> List[Dict[str, str]]:
        return list_pipelines()

    @staticmethod
    def get_current_provider() -> str:
        return normalize_provider_name(os.getenv("RAG_PROVIDER", DEFAULT_PROVIDER))

    @staticmethod
    def has_provider(name: str) -> bool:
        return has_pipeline((name or "").strip().lower())


def _tokenize_for_manifest_search(query: str) -> list[str]:
    import re

    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", query)
    tokens = list(words)
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", word):
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return [token for token in dict.fromkeys(tokens) if token]


def _manifest_content_priority(content_type: str) -> int:
    priorities = {
        "真题": 5,
        "高分作答": 4,
        "示范表达": 3,
        "方法论": 2,
        "论证素材": 1,
    }
    return priorities.get(content_type, 0)
