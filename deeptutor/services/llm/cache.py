"""Deterministic file-based cache for LLM completions.

Small utility used by offline / batch scripts (tag backfill, eval runs) that
call ``deeptutor.services.llm.complete`` many times with the same prompt.
The canonical LLM client does not cache by design — it retries, routes, and
handles live traffic — so scripts should wrap their own calls through
``LLMCache.get_or_fetch`` to avoid burning DeepSeek budget on repeat runs.

Cache layout (one JSON file per entry):

  <root>/<first-2-hex>/<sha256-hex>.json
  {
    "key": "<sha256-hex>",
    "model": "deepseek-chat",
    "prompt": "...",          # truncated to 512 chars for debug auditability
    "system_prompt": "...",   # same
    "response": "...",        # full text
    "created_at": "2026-05-13T...+08:00"
  }

Atomic writes (tmp file + rename) keep the cache safe against partial writes
when a script is interrupted. Corrupted files are treated as misses and
overwritten on next hit.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

_DEFAULT_CACHE_DIR = Path("data/cache/llm")


def _hash_key(*, prompt: str, system_prompt: str, model: str, extra: str) -> str:
    """Deterministic SHA-256 over all inputs that affect the response."""
    hasher = hashlib.sha256()
    for part in (model, system_prompt or "", prompt or "", extra or ""):
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile lets us atomically rename over the target.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp_name = tmp.name
    os.replace(tmp_name, path)


@dataclass
class LLMCache:
    """File-backed LLM completion cache.

    Not thread-safe within a single key — callers are expected to serialise
    ``get_or_fetch`` on the same cache key. Concurrent *different* keys are
    fine because each key writes to its own file.
    """

    root: Path = _DEFAULT_CACHE_DIR

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    def path_for(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(
        self,
        *,
        prompt: str,
        system_prompt: str = "",
        model: str = "default",
        extra: str = "",
    ) -> str | None:
        key = _hash_key(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            extra=extra,
        )
        return self._read(key)

    def set(
        self,
        *,
        prompt: str,
        system_prompt: str = "",
        model: str = "default",
        extra: str = "",
        response: str,
    ) -> None:
        key = _hash_key(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            extra=extra,
        )
        payload = {
            "key": key,
            "model": model,
            "prompt": (prompt or "")[:512],
            "system_prompt": (system_prompt or "")[:512],
            "response": response,
            "created_at": datetime.now().astimezone().isoformat(),
        }
        _atomic_write(self.path_for(key), payload)

    async def get_or_fetch(
        self,
        *,
        prompt: str,
        system_prompt: str = "",
        model: str = "default",
        extra: str = "",
        fetch: Callable[[], Awaitable[str]],
    ) -> tuple[str, bool]:
        """Return cached response or call ``fetch()`` and cache the result.

        Returns ``(response, hit)`` so callers can count API usage for
        budgeting.
        """
        cached = self.get(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            extra=extra,
        )
        if cached is not None:
            return cached, True

        fresh = await fetch()
        self.set(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            extra=extra,
            response=fresh,
        )
        return fresh, False

    def _read(self, key: str) -> str | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt cache entry — treat as miss; next write will replace it.
            return None
        response = data.get("response")
        return response if isinstance(response, str) else None


__all__ = ["LLMCache"]
