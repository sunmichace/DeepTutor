"""Audit picker_snapshot data on stored interview sessions.

Reads ``data/interview/<user_id>/`` for every (or a specified) user and
summarises how the picker influenced question selection over time:

- How often picker hints actually carried into the RAG query.
- Which focus dimensions the picker pushed for, and whether scores on
  those dimensions improved on subsequent sessions.
- Distribution of ``source_kind`` (rag / manifest_fallback /
  unusable_content_fallback / error_fallback) — useful when investigating
  why a learner suddenly starts getting fallback questions.
- Difficulty step decisions (``requested -> effective``).

This is read-only and offline — no LLM, no RAG calls.

Usage:
    python scripts/audit_picker_decisions.py
    python scripts/audit_picker_decisions.py --user u123
    python scripts/audit_picker_decisions.py --output picker_audit.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _interview_root() -> Path:
    return _PROJECT_ROOT / "data" / "interview"


def _list_user_dirs(root: Path, user: str | None) -> list[Path]:
    if not root.exists():
        return []
    if user:
        candidate = root / user
        return [candidate] if candidate.is_dir() else []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _load_sessions(user_dir: Path) -> list[dict[str, Any]]:
    """Return all session JSON files for a user, sorted by completed_at asc."""
    sessions_dir = user_dir / "sessions"
    if not sessions_dir.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            sessions.append(data)
    sessions.sort(
        key=lambda s: str(s.get("completed_at") or s.get("started_at") or "")
    )
    return sessions


def _score_for_dimension(session: dict[str, Any], dimension: str) -> float | None:
    for entry in session.get("scores") or []:
        if isinstance(entry, dict) and str(entry.get("dimension") or "") == dimension:
            try:
                return float(entry.get("score") or 0.0)
            except (TypeError, ValueError):
                return None
    return None


def _summarise_user(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(sessions)
    snapshots = [s.get("picker_snapshot") or {} for s in sessions]
    with_snapshot = sum(1 for snap in snapshots if snap)

    source_kinds = Counter(
        str(snap.get("source_kind") or "<missing>") for snap in snapshots
    )
    diff_decisions = Counter()
    for snap in snapshots:
        req = str(snap.get("requested_difficulty") or "?")
        eff = str(snap.get("effective_difficulty") or "?")
        if req == eff:
            diff_decisions[f"{req}→stay"] += 1
        else:
            diff_decisions[f"{req}→{eff}"] += 1

    focus_per_session: list[list[str]] = []
    for snap in snapshots:
        hints = snap.get("hints") or {}
        focus = hints.get("focus_dimensions") or []
        focus_per_session.append([str(x) for x in focus])

    # Did the focus dimensions actually improve on the next session?
    follow_up_outcomes: list[dict[str, Any]] = []
    for idx, focus in enumerate(focus_per_session[:-1]):
        if not focus:
            continue
        current = sessions[idx]
        nxt = sessions[idx + 1]
        for dim in focus:
            before = _score_for_dimension(current, dim)
            after = _score_for_dimension(nxt, dim)
            if before is None or after is None:
                continue
            follow_up_outcomes.append(
                {
                    "session_id": current.get("session_id"),
                    "next_session_id": nxt.get("session_id"),
                    "dimension": dim,
                    "before": before,
                    "after": after,
                    "delta": round(after - before, 2),
                }
            )

    return {
        "total_sessions": total,
        "with_snapshot": with_snapshot,
        "snapshot_coverage": round(with_snapshot / max(total, 1), 3),
        "source_kinds": dict(source_kinds.most_common()),
        "difficulty_decisions": dict(diff_decisions.most_common()),
        "focus_follow_ups": follow_up_outcomes,
    }


def _render_markdown(reports: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# picker_snapshot audit")
    lines.append("")
    if not reports:
        lines.append("_No interview users found under `data/interview/`._")
        return "\n".join(lines)

    lines.append("| user | sessions | snapshot_coverage | rag / fallback |")
    lines.append("| --- | --- | --- | --- |")
    for user, summary in reports.items():
        rag = summary["source_kinds"].get("rag", 0)
        fallback = sum(
            v for k, v in summary["source_kinds"].items() if k != "rag" and k != "<missing>"
        )
        lines.append(
            f"| `{user}` | {summary['total_sessions']} "
            f"| {summary['with_snapshot']}/{summary['total_sessions']} "
            f"({summary['snapshot_coverage']}) "
            f"| {rag} rag / {fallback} fallback |"
        )
    lines.append("")

    for user, summary in reports.items():
        lines.append(f"## `{user}`")
        lines.append("")
        if summary["source_kinds"]:
            lines.append(
                "**source_kind**: "
                + ", ".join(f"{k}={v}" for k, v in summary["source_kinds"].items())
            )
        if summary["difficulty_decisions"]:
            lines.append(
                "**difficulty**: "
                + ", ".join(f"{k}={v}" for k, v in summary["difficulty_decisions"].items())
            )
        outcomes = summary["focus_follow_ups"]
        if not outcomes:
            lines.append("_no focus follow-ups recorded yet (need ≥ 2 sessions with hints)._")
        else:
            lines.append("")
            lines.append("| dimension | before | after | Δ |")
            lines.append("| --- | --- | --- | --- |")
            for o in outcomes[-12:]:
                arrow = "↑" if o["delta"] > 0 else ("↓" if o["delta"] < 0 else "→")
                lines.append(
                    f"| {o['dimension']} | {o['before']} | {o['after']} "
                    f"| {arrow} {o['delta']:+.2f} |"
                )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=None, help="Audit a single user_id only.")
    parser.add_argument(
        "--root",
        default=str(_interview_root()),
        help="Override interview data root (default: data/interview).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="If given, write a Markdown report to this path; else print to stdout.",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="If given, also write the raw audit data as JSON to this path.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    user_dirs = _list_user_dirs(root, args.user)
    reports: dict[str, dict[str, Any]] = {}
    for user_dir in user_dirs:
        sessions = _load_sessions(user_dir)
        if not sessions:
            continue
        reports[user_dir.name] = _summarise_user(sessions)

    md = _render_markdown(reports)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"audit written to {out}")
    else:
        print(md)

    if args.json_output:
        json_out = Path(args.json_output)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps({"users": reports}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"json audit written to {json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
