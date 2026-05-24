"""Synthesize a 5-session interview history to validate picker V1 end-to-end.

Real live runs cost DeepSeek API tokens. This script writes session JSON
files directly via InterviewMemoryService + write_session_to_memory, so all
the picker-relevant downstream paths (profile aggregation, audit, picker
hint resolution) get exercised against realistic data without spending a
single API call.

The five sessions are crafted to cover every picker V1 branch that needs
≥2 sessions of history:

  s1: low on 论据与案例质量 (qt=综合分析)
  s2: low on 论据与案例质量 (qt=社会现象)        → repeated_weak_dimensions
  s3: 论据与案例质量 climbs to 7                  → resolved (回暖)
  s4: high total score (78)                       → 难度递进 medium → hard
  s5: low total score (42), low on 逻辑完整性     → introduces a fresh weak dim

After running, ``resolve_picker_hints`` should produce non-empty
focus_dimensions / focus_question_types / avoid_question_types and a
non-default suggested_difficulty for at least one (n, n+1) pair.

Usage:
    python scripts/synthesize_picker_sessions.py
    python scripts/synthesize_picker_sessions.py --user picker-v1-synth
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from deeptutor.agents.interview.memory_writer import write_session_to_memory  # noqa: E402
from deeptutor.agents.interview.models import (  # noqa: E402
    DimensionScore,
    InterviewSession,
)
from deeptutor.agents.interview.picker import resolve_picker_hints  # noqa: E402
from deeptutor.services.interview import (  # noqa: E402
    InterviewMemoryService,
    reset_interview_memory_instances,
)


def _score(dim: str, value: float, reason: str = "", evidence: str = "") -> DimensionScore:
    return DimensionScore(
        dimension=dim,
        score=value,
        max_score=10.0,
        deduction_reason=reason,
        evidence=evidence,
    )


def _make_session(
    *,
    user_id: str,
    sid: str,
    qt: str,
    completed_at: str,
    scores: list[DimensionScore],
    suggestion: str,
    picker_query: str = "",
) -> InterviewSession:
    total = round(sum(s.score for s in scores) / len(scores) * 10, 1)
    return InterviewSession(
        session_id=sid,
        user_id=user_id,
        exam_type="公考面试",
        position="公务员",
        question_type=qt,
        difficulty="medium",
        question_text=f"[synthetic] {qt} 模拟题",
        user_answer="[synthetic] 合成作答",
        scores=scores,
        total_score=total,
        review_report=f"[synthetic review] qt={qt} total={total}",
        training_suggestion=suggestion,
        started_at=completed_at,
        completed_at=completed_at,
        picker_snapshot={
            "hints": {"reason": "synthesized"},
            "requested_difficulty": "medium",
            "effective_difficulty": "medium",
            "source_kind": "synthesized",
            "reranked_sources": [],
            "query": picker_query or f"{qt} 面试题 公务员 medium",
        },
    )


def _build_sessions(user_id: str) -> list[InterviewSession]:
    """5 sessions in chronological order."""
    return [
        # s1: low on 论据 — first appearance
        _make_session(
            user_id=user_id,
            sid="synth-s1",
            qt="综合分析",
            completed_at="2026-05-19T10:00:00+08:00",
            scores=[
                _score("审题与立意", 6.0),
                _score("结构化表达", 6.0),
                _score("逻辑完整性", 6.0),
                _score("论据与案例质量", 4.0, "案例缺失"),
                _score("岗位匹配度", 5.0, "对公务员场景理解浅"),
                _score("语言自然度", 7.0),
                _score("临场应对", 7.0),
                _score("追问应答质量", 8.0),
            ],
            suggestion="积累 5 个基层治理案例，每周精读 2 个。",
        ),
        # s2: low on 论据 — second appearance → triggers repeated_weak_dimensions
        _make_session(
            user_id=user_id,
            sid="synth-s2",
            qt="社会现象",
            completed_at="2026-05-20T10:00:00+08:00",
            scores=[
                _score("审题与立意", 7.0),
                _score("结构化表达", 6.0),
                _score("逻辑完整性", 6.0),
                _score("论据与案例质量", 4.0, "案例仍偏空"),
                _score("岗位匹配度", 6.0),
                _score("语言自然度", 7.0),
                _score("临场应对", 7.0),
                _score("追问应答质量", 8.0),
            ],
            suggestion="按题型整理 2 个可复用案例，重点练'社会现象'类。",
        ),
        # s3: 论据 climbs ≥ 6 → moves to resolved_dimensions
        _make_session(
            user_id=user_id,
            sid="synth-s3",
            qt="综合分析",
            completed_at="2026-05-21T10:00:00+08:00",
            scores=[
                _score("审题与立意", 7.0),
                _score("结构化表达", 7.0),
                _score("逻辑完整性", 7.0),
                _score("论据与案例质量", 7.0),
                _score("岗位匹配度", 7.0),
                _score("语言自然度", 8.0),
                _score("临场应对", 7.0),
                _score("追问应答质量", 8.0),
            ],
            suggestion="保持现有节奏，论据维度可持续巩固。",
        ),
        # s4: high total → triggers difficulty bump on next start
        _make_session(
            user_id=user_id,
            sid="synth-s4",
            qt="组织管理",
            completed_at="2026-05-22T10:00:00+08:00",
            scores=[
                _score("审题与立意", 8.0),
                _score("结构化表达", 8.0),
                _score("逻辑完整性", 8.0),
                _score("论据与案例质量", 8.0),
                _score("岗位匹配度", 7.0),
                _score("语言自然度", 8.0),
                _score("临场应对", 8.0),
                _score("追问应答质量", 8.0),
            ],
            suggestion="开始尝试更复杂的多任务场景题。",
        ),
        # s5: 逻辑完整性 dips low — fresh weak dim emerging
        _make_session(
            user_id=user_id,
            sid="synth-s5",
            qt="计划组织",
            completed_at="2026-05-23T10:00:00+08:00",
            scores=[
                _score("审题与立意", 6.0),
                _score("结构化表达", 6.0),
                _score("逻辑完整性", 4.0, "环节衔接断裂"),
                _score("论据与案例质量", 6.0),
                _score("岗位匹配度", 6.0),
                _score("语言自然度", 7.0),
                _score("临场应对", 6.0),
                _score("追问应答质量", 7.0),
            ],
            suggestion="计划组织题先列时间轴再补细节，强制自查环节衔接。",
        ),
    ]


async def _run(user_id: str, fresh: bool) -> int:
    if fresh:
        user_dir = _PROJECT_ROOT / "data" / "interview" / user_id
        if user_dir.exists():
            shutil.rmtree(user_dir)
            print(f"removed existing {user_dir}")

    reset_interview_memory_instances()
    svc = InterviewMemoryService(user_id=user_id)

    sessions = _build_sessions(user_id)
    for session in sessions:
        await write_session_to_memory(session=session, memory_service=svc)
        print(f"  wrote {session.session_id} qt={session.question_type} total={session.total_score}")

    profile = svc.read_profile()
    recent = svc.get_recent_sessions(limit=5)

    print()
    print("=== profile.dynamic ===")
    d = profile.dynamic
    print("  repeated_weak_dimensions:", [x.get("dimension") for x in d.repeated_weak_dimensions])
    print("  resolved_dimensions:     ", [x.get("dimension") for x in d.resolved_dimensions])
    print("  recent_weak_types:       ", d.recent_weak_types)
    trends = {t["dimension"]: t["status"] for t in d.dimension_trends}
    print("  dimension_trends:        ", trends)
    print("  recent_trend:            ", d.recent_trend)

    print()
    print("=== picker hints (next session would see) ===")
    for diff in ("medium", "hard", "easy"):
        hints = resolve_picker_hints(
            profile=profile,
            recent_sessions=recent,
            requested_difficulty=diff,
        )
        print(f"  requested={diff}:")
        print(f"    focus_dimensions:      {hints.focus_dimensions}")
        print(f"    focus_question_types:  {hints.focus_question_types}")
        print(f"    avoid_question_types:  {hints.avoid_question_types}")
        print(f"    suggested_difficulty:  {hints.suggested_difficulty}")
        print(f"    reason:                {hints.reason}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="picker-v1-synth")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Don't wipe the user's existing data before writing.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.user, fresh=not args.keep))


if __name__ == "__main__":
    sys.exit(main())
