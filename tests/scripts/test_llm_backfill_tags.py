from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "llm_backfill_tags.py"
    spec = importlib.util.spec_from_file_location("llm_backfill_tags_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so dataclass decoration (Python 3.12) can resolve
    # forward refs via cls.__module__.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_is_sentinel_covers_empty_default_and_generic():
    mod = _load_module()
    assert mod._is_sentinel("estimated_question_type", "")
    assert mod._is_sentinel("estimated_question_type", "综合课程")
    assert mod._is_sentinel("estimated_question_type", "综合套题")
    assert mod._is_sentinel("estimated_question_type", "经验笔记")
    assert not mod._is_sentinel("estimated_question_type", "社会现象")

    assert mod._is_sentinel("estimated_position", "")
    assert mod._is_sentinel("estimated_position", "通用")
    assert mod._is_sentinel("estimated_position", "综合管理")
    assert not mod._is_sentinel("estimated_position", "公务员")

    assert mod._is_sentinel("estimated_difficulty", "medium")
    assert not mod._is_sentinel("estimated_difficulty", "hard")


def test_needs_backfill_detects_any_sentinel_field():
    mod = _load_module()
    clean = {
        "estimated_question_type": "社会现象",
        "estimated_position": "公务员",
        "estimated_difficulty": "hard",
    }
    assert not mod._needs_backfill(clean)

    dirty = {**clean, "estimated_difficulty": "medium"}
    assert mod._needs_backfill(dirty)


def test_build_prompt_surfaces_current_tags_and_candidates():
    mod = _load_module()
    entry = {
        "file_name": "综合课程.pdf",
        "relative_path": "input/综合课程.pdf",
        "source_kind": "original_raw",
        "estimated_question_type": "综合课程",
        "estimated_position": "公务员",
        "estimated_difficulty": "medium",
    }
    prompt = mod._build_prompt(entry)
    assert "综合课程.pdf" in prompt
    assert "社会现象" in prompt  # one of the candidates
    assert "easy" in prompt and "hard" in prompt


def test_parse_response_rejects_non_json_and_invalid_schema():
    mod = _load_module()
    assert mod._parse_response("nothing here") is None
    assert mod._parse_response("{bad json") is None
    # confidence out of range -> ValidationError -> None
    assert mod._parse_response('{"confidence": 2.5}') is None


def test_parse_response_accepts_valid_payload():
    mod = _load_module()
    raw = (
        "解释性前缀被忽略。"
        '{"question_type": "社会现象", "position": "公务员", '
        '"difficulty": "hard", "confidence": 0.82, "reason": "真题类标题"}'
    )
    suggestion = mod._parse_response(raw)
    assert suggestion is not None
    assert suggestion.question_type == "社会现象"
    assert suggestion.confidence == 0.82


def test_apply_suggestion_only_fills_sentinel_fields_by_default():
    mod = _load_module()
    entry = {
        "estimated_question_type": "社会现象",
        "estimated_position": "通用",
        "estimated_difficulty": "medium",
    }
    suggestion = mod.TagSuggestion(
        question_type="真题",          # ignored because entry already has 社会现象
        position="公务员",             # fills default 通用
        difficulty="hard",             # fills default medium
        confidence=0.9,
        reason="file name hints",
    )
    applied = mod._apply_suggestion(entry, suggestion, overwrite=False)
    assert set(applied) == {"estimated_position", "estimated_difficulty"}
    assert entry["estimated_question_type"] == "社会现象"
    assert entry["estimated_position"] == "公务员"
    assert entry["estimated_difficulty"] == "hard"
    assert entry["_llm_backfill"][mod._SCHEMA_VERSION]["confidence"] == 0.9


def test_apply_suggestion_overwrite_replaces_strong_values():
    mod = _load_module()
    entry = {
        "estimated_question_type": "社会现象",
        "estimated_position": "公务员",
    }
    suggestion = mod.TagSuggestion(
        question_type="真题",
        position="省考",
        difficulty="",
        confidence=0.75,
    )
    mod._apply_suggestion(entry, suggestion, overwrite=True)
    assert entry["estimated_question_type"] == "真题"
    assert entry["estimated_position"] == "省考"


def test_apply_suggestion_rejects_values_outside_candidate_set():
    mod = _load_module()
    entry = {"estimated_position": ""}
    suggestion = mod.TagSuggestion(position="海淀街道办", confidence=0.99)
    applied = mod._apply_suggestion(entry, suggestion, overwrite=True)
    assert applied == []
    assert entry["estimated_position"] == ""


def test_dry_run_does_not_call_llm_or_write_manifest(tmp_path: Path):
    mod = _load_module()
    manifest = {
        "kb_name": "interview_bank",
        "files": [
            {
                "file_name": "unk.pdf",
                "relative_path": "input/unk.pdf",
                "source_kind": "original_raw",
                "estimated_question_type": "综合课程",
                "estimated_position": "通用",
                "estimated_difficulty": "medium",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    cache_dir = tmp_path / "cache"

    rc = mod.main(
        [
            "--manifest",
            str(manifest_path),
            "--cache-dir",
            str(cache_dir),
            "--dry-run",
        ]
    )
    assert rc == 0
    # Manifest on disk is untouched.
    reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert reloaded == manifest
    # Cache directory may not even exist in pure dry-run.
    assert not list(cache_dir.rglob("*.json")) if cache_dir.exists() else True


def test_cache_hit_skips_live_call_and_applies_updates(tmp_path: Path, monkeypatch):
    mod = _load_module()
    manifest = {
        "kb_name": "interview_bank",
        "files": [
            {
                "file_name": "target.pdf",
                "relative_path": "input/target.pdf",
                "source_kind": "original_raw",
                "estimated_question_type": "综合课程",
                "estimated_position": "通用",
                "estimated_difficulty": "medium",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    cache_dir = tmp_path / "cache"

    # Prime the cache with a canned response so no LLM call is needed.
    from deeptutor.services.llm.cache import LLMCache

    cache = LLMCache(root=cache_dir)
    prompt = mod._build_prompt(manifest["files"][0])
    cache.set(
        prompt=prompt,
        system_prompt=mod._SYSTEM_PROMPT,
        model="deepseek-chat",
        extra=mod._SCHEMA_VERSION,
        response=json.dumps(
            {
                "question_type": "真题",
                "position": "公务员",
                "difficulty": "hard",
                "confidence": 0.9,
                "reason": "cached",
            },
            ensure_ascii=False,
        ),
    )

    # Fail loudly if the script ever tries to call the live LLM.
    import deeptutor.services.llm as llm_pkg

    def _should_not_be_called(*_a, **_kw):
        raise AssertionError("live LLM must not be invoked on cache hit")

    monkeypatch.setattr(llm_pkg, "complete", _should_not_be_called)

    rc = mod.main(
        [
            "--manifest",
            str(manifest_path),
            "--cache-dir",
            str(cache_dir),
            "--commit",
            "--max-api-calls",
            "5",
        ]
    )
    assert rc == 0

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = updated["files"][0]
    assert entry["estimated_question_type"] == "真题"
    assert entry["estimated_position"] == "公务员"
    assert entry["estimated_difficulty"] == "hard"
    assert entry["_llm_backfill"][mod._SCHEMA_VERSION]["applied"]


def test_max_api_calls_zero_disables_live_calls(tmp_path: Path, monkeypatch):
    mod = _load_module()
    manifest = {
        "kb_name": "interview_bank",
        "files": [
            {
                "file_name": "nocache.pdf",
                "relative_path": "input/nocache.pdf",
                "source_kind": "original_raw",
                "estimated_question_type": "综合课程",
                "estimated_position": "通用",
                "estimated_difficulty": "medium",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    cache_dir = tmp_path / "cache"

    import deeptutor.services.llm as llm_pkg

    def _fail(*_a, **_kw):
        raise AssertionError("should not call LLM when max_api_calls=0")

    monkeypatch.setattr(llm_pkg, "complete", _fail)

    rc = mod.main(
        [
            "--manifest",
            str(manifest_path),
            "--cache-dir",
            str(cache_dir),
            "--commit",
            "--max-api-calls",
            "0",
        ]
    )
    assert rc == 0
    reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert reloaded == manifest
