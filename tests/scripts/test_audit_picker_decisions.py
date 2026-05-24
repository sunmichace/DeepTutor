from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "audit_picker_decisions.py"
    spec = importlib.util.spec_from_file_location(
        "audit_picker_decisions_under_test", module_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_session(
    *,
    sid: str,
    completed_at: str,
    snapshot: dict | None = None,
    scores: list[dict] | None = None,
) -> dict:
    return {
        "session_id": sid,
        "user_id": "u1",
        "completed_at": completed_at,
        "scores": scores or [],
        "picker_snapshot": snapshot or {},
    }


def _write_session(user_dir: Path, session: dict) -> None:
    sessions_dir = user_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / f"{session['session_id']}.json").write_text(
        json.dumps(session, ensure_ascii=False), encoding="utf-8"
    )


def test_load_sessions_sorts_by_completed_at(tmp_path: Path):
    mod = _load_module()
    user_dir = tmp_path / "u1"
    _write_session(user_dir, _make_session(sid="s2", completed_at="2026-05-02T10:00:00+08:00"))
    _write_session(user_dir, _make_session(sid="s1", completed_at="2026-05-01T10:00:00+08:00"))
    _write_session(user_dir, _make_session(sid="s3", completed_at="2026-05-03T10:00:00+08:00"))

    sessions = mod._load_sessions(user_dir)
    assert [s["session_id"] for s in sessions] == ["s1", "s2", "s3"]


def test_load_sessions_skips_corrupt_files(tmp_path: Path):
    mod = _load_module()
    user_dir = tmp_path / "u1"
    _write_session(user_dir, _make_session(sid="ok", completed_at="2026-05-01T10:00:00+08:00"))
    (user_dir / "sessions" / "broken.json").write_text("{not json", encoding="utf-8")

    sessions = mod._load_sessions(user_dir)
    assert [s["session_id"] for s in sessions] == ["ok"]


def test_summarise_user_counts_source_kind_and_difficulty(tmp_path: Path):
    mod = _load_module()
    sessions = [
        _make_session(
            sid="s1",
            completed_at="2026-05-01T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "requested_difficulty": "medium",
                "effective_difficulty": "hard",
                "hints": {"focus_dimensions": []},
            },
        ),
        _make_session(
            sid="s2",
            completed_at="2026-05-02T10:00:00+08:00",
            snapshot={
                "source_kind": "manifest_fallback",
                "requested_difficulty": "medium",
                "effective_difficulty": "medium",
                "hints": {"focus_dimensions": []},
            },
        ),
        _make_session(
            sid="s3",
            completed_at="2026-05-03T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "requested_difficulty": "easy",
                "effective_difficulty": "easy",
                "hints": {"focus_dimensions": []},
            },
        ),
    ]
    summary = mod._summarise_user(sessions)
    assert summary["total_sessions"] == 3
    assert summary["with_snapshot"] == 3
    assert summary["snapshot_coverage"] == 1.0
    assert summary["source_kinds"] == {"rag": 2, "manifest_fallback": 1}
    assert summary["difficulty_decisions"] == {
        "medium→hard": 1,
        "medium→stay": 1,
        "easy→stay": 1,
    }


def test_summarise_user_links_focus_to_next_session_score():
    mod = _load_module()
    sessions = [
        _make_session(
            sid="s1",
            completed_at="2026-05-01T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "hints": {"focus_dimensions": ["论据与案例质量"]},
            },
            scores=[
                {"dimension": "论据与案例质量", "score": 4.0},
            ],
        ),
        _make_session(
            sid="s2",
            completed_at="2026-05-02T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "hints": {"focus_dimensions": ["论据与案例质量"]},
            },
            scores=[
                {"dimension": "论据与案例质量", "score": 7.0},
            ],
        ),
        _make_session(
            sid="s3",
            completed_at="2026-05-03T10:00:00+08:00",
            snapshot={"source_kind": "rag", "hints": {"focus_dimensions": []}},
            scores=[
                {"dimension": "论据与案例质量", "score": 8.0},
            ],
        ),
    ]
    summary = mod._summarise_user(sessions)
    follow_ups = summary["focus_follow_ups"]
    assert len(follow_ups) == 2
    # s1 → s2: 4 → 7, +3
    assert follow_ups[0]["session_id"] == "s1"
    assert follow_ups[0]["dimension"] == "论据与案例质量"
    assert follow_ups[0]["before"] == 4.0
    assert follow_ups[0]["after"] == 7.0
    assert follow_ups[0]["delta"] == 3.0
    # s2 → s3: 7 → 8, +1
    assert follow_ups[1]["delta"] == 1.0


def test_summarise_user_skips_focus_when_dimension_missing():
    mod = _load_module()
    sessions = [
        _make_session(
            sid="s1",
            completed_at="2026-05-01T10:00:00+08:00",
            snapshot={"hints": {"focus_dimensions": ["论据与案例质量"]}},
            scores=[{"dimension": "其他维度", "score": 4.0}],
        ),
        _make_session(
            sid="s2",
            completed_at="2026-05-02T10:00:00+08:00",
            snapshot={"hints": {"focus_dimensions": []}},
            scores=[{"dimension": "其他维度", "score": 5.0}],
        ),
    ]
    summary = mod._summarise_user(sessions)
    # Focus dimension missing in either side → no follow-up entry.
    assert summary["focus_follow_ups"] == []


def test_main_writes_markdown_report(tmp_path: Path):
    mod = _load_module()
    root = tmp_path / "interview"
    user_dir = root / "u1"
    _write_session(
        user_dir,
        _make_session(
            sid="s1",
            completed_at="2026-05-01T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "requested_difficulty": "medium",
                "effective_difficulty": "hard",
                "hints": {"focus_dimensions": ["论据与案例质量"]},
            },
            scores=[{"dimension": "论据与案例质量", "score": 4.0}],
        ),
    )
    _write_session(
        user_dir,
        _make_session(
            sid="s2",
            completed_at="2026-05-02T10:00:00+08:00",
            snapshot={
                "source_kind": "manifest_fallback",
                "requested_difficulty": "medium",
                "effective_difficulty": "medium",
                "hints": {"focus_dimensions": []},
            },
            scores=[{"dimension": "论据与案例质量", "score": 7.0}],
        ),
    )
    output = tmp_path / "audit.md"
    rc = mod.main(
        [
            "--root",
            str(root),
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    text = output.read_text(encoding="utf-8")
    assert text.startswith("# picker_snapshot audit")
    assert "u1" in text
    assert "rag" in text and "manifest_fallback" in text
    assert "论据与案例质量" in text


def test_main_handles_missing_root_gracefully(tmp_path: Path, capsys):
    mod = _load_module()
    rc = mod.main(["--root", str(tmp_path / "does_not_exist")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No interview users" in out


def test_main_writes_json_output_alongside_markdown(tmp_path: Path):
    mod = _load_module()
    root = tmp_path / "interview"
    user_dir = root / "u_json"
    _write_session(
        user_dir,
        _make_session(
            sid="s1",
            completed_at="2026-05-01T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "requested_difficulty": "medium",
                "effective_difficulty": "hard",
                "hints": {"focus_dimensions": []},
            },
        ),
    )
    md_path = tmp_path / "audit.md"
    json_path = tmp_path / "audit.json"

    rc = mod.main(
        [
            "--root",
            str(root),
            "--output",
            str(md_path),
            "--json-output",
            str(json_path),
        ]
    )
    assert rc == 0
    assert md_path.exists() and md_path.stat().st_size > 0
    assert json_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "u_json" in payload["users"]
    summary = payload["users"]["u_json"]
    assert summary["total_sessions"] == 1
    assert summary["source_kinds"] == {"rag": 1}
    assert summary["difficulty_decisions"] == {"medium→hard": 1}


def test_aggregate_returns_zero_for_empty_reports():
    mod = _load_module()
    agg = mod._aggregate({})
    assert agg["user_count"] == 0
    assert agg["total_sessions"] == 0
    assert agg["overall_coverage"] == 0.0
    assert agg["users_full_coverage"] == 0
    assert agg["users_zero_coverage"] == 0


def test_aggregate_rolls_up_per_user_summaries():
    mod = _load_module()
    sessions_a = [
        _make_session(
            sid=f"a{i}",
            completed_at=f"2026-05-0{i+1}T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "requested_difficulty": "medium",
                "effective_difficulty": "medium",
                "hints": {"focus_dimensions": []},
            },
        )
        for i in range(2)
    ]
    sessions_b = [
        _make_session(
            sid="b1",
            completed_at="2026-05-01T10:00:00+08:00",
            snapshot={
                "source_kind": "manifest_fallback",
                "requested_difficulty": "medium",
                "effective_difficulty": "hard",
                "hints": {"focus_dimensions": []},
            },
        ),
    ]
    sessions_c = [
        _make_session(sid="c1", completed_at="2026-05-01T10:00:00+08:00", snapshot={}),
    ]
    reports = {
        "user_a": mod._summarise_user(sessions_a),
        "user_b": mod._summarise_user(sessions_b),
        "user_c": mod._summarise_user(sessions_c),
    }
    agg = mod._aggregate(reports)
    assert agg["user_count"] == 3
    assert agg["total_sessions"] == 4
    assert agg["total_with_snapshot"] == 3            # only c has empty snapshot
    assert agg["overall_coverage"] == round(3 / 4, 3)
    assert agg["users_full_coverage"] == 2            # a & b
    assert agg["users_zero_coverage"] == 1            # c
    assert agg["source_kinds"] == {"rag": 2, "manifest_fallback": 1, "<missing>": 1}
    assert agg["difficulty_decisions"] == {"medium→stay": 2, "medium→hard": 1, "?→stay": 1}
    assert agg["mean_sessions_per_user"] == round(4 / 3, 2)


def test_render_markdown_includes_fleet_aggregate_section(tmp_path: Path):
    mod = _load_module()
    root = tmp_path / "interview"
    user_dir = root / "u_agg"
    _write_session(
        user_dir,
        _make_session(
            sid="s1",
            completed_at="2026-05-01T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "requested_difficulty": "medium",
                "effective_difficulty": "hard",
                "hints": {"focus_dimensions": []},
            },
        ),
    )
    output = tmp_path / "out.md"
    mod.main(["--root", str(root), "--output", str(output)])
    md = output.read_text(encoding="utf-8")
    assert "## Fleet aggregate" in md
    assert "**users**: 1" in md
    assert "**sessions**: 1" in md
    assert "**overall picker_snapshot coverage**: 1/1" in md
    assert "**users at full coverage**: 1 / 1" in md
    assert "**users at zero coverage**: 0 / 1" in md
    assert "## Per-user" in md


def test_main_json_output_contains_aggregate(tmp_path: Path):
    mod = _load_module()
    root = tmp_path / "interview"
    user_dir = root / "u_agg_json"
    _write_session(
        user_dir,
        _make_session(
            sid="s1",
            completed_at="2026-05-01T10:00:00+08:00",
            snapshot={
                "source_kind": "rag",
                "requested_difficulty": "medium",
                "effective_difficulty": "medium",
                "hints": {"focus_dimensions": []},
            },
        ),
    )
    md_path = tmp_path / "out.md"
    json_path = tmp_path / "out.json"
    mod.main([
        "--root", str(root),
        "--output", str(md_path),
        "--json-output", str(json_path),
    ])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "users" in payload
    assert "aggregate" in payload
    assert payload["aggregate"]["user_count"] == 1
    assert payload["aggregate"]["total_sessions"] == 1
    assert payload["aggregate"]["overall_coverage"] == 1.0
