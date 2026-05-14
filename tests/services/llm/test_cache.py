from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deeptutor.services.llm.cache import LLMCache


def test_get_returns_none_for_missing_key(tmp_path: Path):
    cache = LLMCache(root=tmp_path)
    assert cache.get(prompt="hello", model="m1") is None


def test_set_then_get_round_trip(tmp_path: Path):
    cache = LLMCache(root=tmp_path)
    cache.set(prompt="hello", system_prompt="sys", model="m1", response="hi there")
    assert cache.get(prompt="hello", system_prompt="sys", model="m1") == "hi there"


def test_keys_are_input_sensitive(tmp_path: Path):
    cache = LLMCache(root=tmp_path)
    cache.set(prompt="hello", model="m1", response="A")
    cache.set(prompt="hello", model="m2", response="B")
    cache.set(prompt="hello", system_prompt="x", model="m1", response="C")
    cache.set(prompt="hello", model="m1", extra="v2", response="D")
    assert cache.get(prompt="hello", model="m1") == "A"
    assert cache.get(prompt="hello", model="m2") == "B"
    assert cache.get(prompt="hello", system_prompt="x", model="m1") == "C"
    assert cache.get(prompt="hello", model="m1", extra="v2") == "D"


def test_corrupt_file_is_treated_as_miss(tmp_path: Path):
    cache = LLMCache(root=tmp_path)
    cache.set(prompt="hello", model="m1", response="ok")
    target = next(tmp_path.rglob("*.json"))
    target.write_text("{not valid json", encoding="utf-8")
    assert cache.get(prompt="hello", model="m1") is None
    # Subsequent set replaces the corrupt entry.
    cache.set(prompt="hello", model="m1", response="recovered")
    assert cache.get(prompt="hello", model="m1") == "recovered"


def test_set_payload_truncates_for_audit(tmp_path: Path):
    cache = LLMCache(root=tmp_path)
    long_prompt = "x" * 10_000
    long_system = "y" * 10_000
    cache.set(
        prompt=long_prompt,
        system_prompt=long_system,
        model="m1",
        response="short",
    )
    target = next(tmp_path.rglob("*.json"))
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert len(payload["prompt"]) == 512
    assert len(payload["system_prompt"]) == 512
    # Response is preserved in full so callers retrieve correct content.
    assert payload["response"] == "short"


def test_get_or_fetch_calls_fetch_only_on_miss(tmp_path: Path):
    cache = LLMCache(root=tmp_path)
    calls = {"count": 0}

    async def fetch() -> str:
        calls["count"] += 1
        return "from-llm"

    async def _run():
        first, hit1 = await cache.get_or_fetch(prompt="p", model="m", fetch=fetch)
        second, hit2 = await cache.get_or_fetch(prompt="p", model="m", fetch=fetch)
        return first, hit1, second, hit2

    first, hit1, second, hit2 = asyncio.run(_run())
    assert calls["count"] == 1
    assert (first, hit1) == ("from-llm", False)
    assert (second, hit2) == ("from-llm", True)


def test_set_is_atomic_under_partial_write_simulation(tmp_path: Path, monkeypatch):
    cache = LLMCache(root=tmp_path)
    cache.set(prompt="p", model="m", response="ok")

    # Force the next _atomic_write to fail mid-flight.
    from deeptutor.services.llm import cache as cache_mod

    real_replace = cache_mod.os.replace

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(cache_mod.os, "replace", boom)
    with pytest.raises(RuntimeError):
        cache.set(prompt="p", model="m", response="new")

    # Restore replace to verify the original cached value is intact.
    monkeypatch.setattr(cache_mod.os, "replace", real_replace)
    assert cache.get(prompt="p", model="m") == "ok"
