"""User isolation tests — verify that multiple users' interview memory
does not leak between users at any level.

This is a security-sensitive test suite: any failure here indicates
a data leak that must be fixed before production.
"""

from __future__ import annotations

from deeptutor.services.interview.models import InterviewSession
from deeptutor.services.interview import (
    DynamicProfile,
    InterviewMemoryService,
    LearnerProfile,
    StableProfile,
    reset_interview_memory_instances,
)


def setup_module():
    reset_interview_memory_instances()


def _make_users() -> list[InterviewMemoryService]:
    """Create 3 users with distinct profiles and sessions."""
    users = {
        "alice": LearnerProfile(
            stable=StableProfile(target_exam_type="国考", target_position="税务"),
            dynamic=DynamicProfile(recent_weak_types=["综合分析"]),
        ),
        "bob": LearnerProfile(
            stable=StableProfile(target_exam_type="省考", target_position="公安"),
            dynamic=DynamicProfile(recent_weak_types=["计划组织", "应急应变"]),
        ),
        "carol": LearnerProfile(
            stable=StableProfile(target_exam_type="事业编", target_position="教师岗"),
            dynamic=DynamicProfile(recent_weak_types=["人际沟通"]),
        ),
    }
    services = {}
    for uid, profile in users.items():
        svc = InterviewMemoryService(uid)
        svc.save_profile(profile)
        svc.save_session(InterviewSession(
            session_id=f"{uid}_s1",
            user_id=uid,
            question_type="综合分析",
            total_score=60.0,
        ))
        services[uid] = svc
    return services


def test_profile_isolation() -> None:
    """Each user can only read their own profile."""
    services = _make_users()

    for uid, svc in services.items():
        profile = svc.read_profile()
        # Alice should see only her data
        assert profile.stable.target_exam_type in ("国考", "省考", "事业编")
        # Verify no cross-contamination by checking exact values
        if uid == "alice":
            assert profile.stable.target_position == "税务"
        elif uid == "bob":
            assert profile.stable.target_position == "公安"
        elif uid == "carol":
            assert profile.stable.target_position == "教师岗"


def test_session_isolation() -> None:
    """Each user can only list their own sessions."""
    services = _make_users()

    for uid, svc in services.items():
        sessions = svc.list_sessions()
        for s in sessions:
            # Session IDs are prefixed with username
            assert s["session_id"].startswith(uid), (
                f"User {uid} can see session {s['session_id']} belonging to another user!"
            )


def test_cannot_read_other_user_session() -> None:
    """Direct read of another user's session ID returns None."""
    services = _make_users()

    # Alice tries to read Bob's session
    alice_svc = services["alice"]
    bob_session = alice_svc.read_session("bob_s1")
    assert bob_session is None, "Alice should not be able to read Bob's session"


def test_directory_isolation() -> None:
    """Verify that storage directories are user-specific."""
    from pathlib import Path
    from deeptutor.services.path_service import get_path_service

    root = get_path_service().project_root / "data" / "interview"
    # Remove any service that was created in other tests to avoid cross-test pollution
    assert (root / "alice").exists()
    assert (root / "bob").exists()
    assert (root / "carol").exists()

    # Verify that alice's directory doesn't contain bob's session
    alice_session_dir = root / "alice" / "sessions"
    if alice_session_dir.exists():
        alice_files = {f.name for f in alice_session_dir.iterdir() if f.suffix == ".json"}
        for f in alice_files:
            assert not f.startswith("bob_"), f"Alice's session dir contains Bob's session: {f}"
            assert not f.startswith("carol_"), f"Alice's session dir contains Carol's session: {f}"


def test_clear_profile_only_affects_one_user() -> None:
    """Clearing one user's profile does not affect others."""
    services = _make_users()

    # Clear Alice's profile
    services["alice"].clear_profile()

    # Alice's profile should be empty
    assert services["alice"].read_profile().stable.target_exam_type == ""

    # Bob's profile should be intact
    assert services["bob"].read_profile().stable.target_exam_type == "省考"
    assert services["bob"].read_profile().stable.target_position == "公安"


def test_clear_all_sessions_only_affects_one_user() -> None:
    """Clearing one user's sessions does not affect others."""
    services = _make_users()

    # Clear Bob's sessions
    services["bob"].clear_all_sessions()

    # Bob should have 0 sessions
    assert services["bob"].count_sessions() == 0

    # Alice and carol should still have their sessions
    assert services["alice"].count_sessions() == 1
    assert services["carol"].count_sessions() == 1
