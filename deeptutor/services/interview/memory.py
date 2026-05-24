"""InterviewMemoryService — per-user interview memory with learner profile.

Storage layout (JSON files per user):
  data/interview/{user_id}/
    profile.json           # StableProfile + DynamicProfile
    sessions/
      {session_id}.json    # Individual interview session records
    sessions_index.json    # Lightweight index of all sessions
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from deeptutor.logging import Logger, get_logger
from deeptutor.services.path_service import get_path_service

from .models import (
    DynamicProfile,
    InterviewSession,
    LearnerProfile,
    StableProfile,
)

_PROFILE_FILE = "profile.json"
_SESSIONS_DIR = "sessions"
_SESSIONS_INDEX = "sessions_index.json"
_ACTIVE_SESSION_FILE = "active_session.json"

logger: Logger = get_logger("InterviewMemory")


class InterviewMemoryService:
    """Per-user interview memory with structured learner profile and session storage."""

    def __init__(self, user_id: str = "default") -> None:
        self._user_id = user_id
        root = get_path_service().project_root / "data" / "interview"
        self._user_dir = root / user_id
        self._user_dir.mkdir(parents=True, exist_ok=True)

    # ── Profile ────────────────────────────────────────────────────────

    def save_profile(self, profile: LearnerProfile) -> None:
        """Persist the full learner profile."""
        path = self._user_dir / _PROFILE_FILE
        now = datetime.now().astimezone().isoformat()
        profile.stable.updated_at = now
        profile.dynamic.updated_at = now
        path.write_text(
            json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_profile(self) -> LearnerProfile:
        """Read the learner profile, returning an empty one if none exists."""
        path = self._user_dir / _PROFILE_FILE
        if not path.exists():
            return LearnerProfile.empty()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return LearnerProfile.from_dict(data)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning(f"Failed to read profile for user {self._user_id}: {exc}")
            return LearnerProfile.empty()

    def update_stable_profile(self, **kwargs: Any) -> StableProfile:
        """Update specific stable profile fields in-place."""
        profile = self.read_profile()
        for key, value in kwargs.items():
            if hasattr(profile.stable, key):
                setattr(profile.stable, key, value)
        self.save_profile(profile)
        return profile.stable

    def update_dynamic_profile(self, **kwargs: Any) -> DynamicProfile:
        """Update specific dynamic profile fields in-place."""
        profile = self.read_profile()
        for key, value in kwargs.items():
            if hasattr(profile.dynamic, key):
                setattr(profile.dynamic, key, value)
        self.save_profile(profile)
        return profile.dynamic

    def clear_profile(self) -> None:
        """Reset the learner profile to empty."""
        path = self._user_dir / _PROFILE_FILE
        if path.exists():
            path.unlink()

    # ── Sessions ───────────────────────────────────────────────────────

    def save_session(self, session: InterviewSession) -> None:
        """Persist a single interview session."""
        sessions_dir = self._user_dir / _SESSIONS_DIR
        sessions_dir.mkdir(parents=True, exist_ok=True)

        session_path = sessions_dir / f"{session.session_id}.json"
        session_path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._update_session_index(session)

    def read_session(self, session_id: str) -> InterviewSession | None:
        """Read a single interview session by ID."""
        path = self._user_dir / _SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return InterviewSession.from_dict(data)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning(f"Failed to read session {session_id}: {exc}")
            return None

    def save_active_session(self, session: InterviewSession) -> None:
        """Persist the in-progress session for this user."""
        path = self._user_dir / _ACTIVE_SESSION_FILE
        path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_active_session(self) -> InterviewSession | None:
        """Read the in-progress session for this user, if one exists."""
        path = self._user_dir / _ACTIVE_SESSION_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return InterviewSession.from_dict(data)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning(f"Failed to read active session for user {self._user_id}: {exc}")
            return None

    def clear_active_session(self) -> None:
        """Remove the in-progress session marker for this user."""
        path = self._user_dir / _ACTIVE_SESSION_FILE
        if path.exists():
            path.unlink()

    def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
        question_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List session summaries, newest first, with optional type filter."""
        index = self._read_session_index()
        sessions: list[dict[str, Any]] = index.get("sessions", [])

        # Filter by question type if specified
        if question_type:
            sessions = [s for s in sessions if s.get("question_type") == question_type]

        # Sort by completion time descending
        sessions.sort(key=lambda s: s.get("completed_at", ""), reverse=True)

        return sessions[offset:offset + limit]

    def count_sessions(self, question_type: str | None = None) -> int:
        """Count total sessions (optionally filtered by question type)."""
        index = self._read_session_index()
        sessions = index.get("sessions", [])
        if question_type:
            return sum(1 for s in sessions if s.get("question_type") == question_type)
        return len(sessions)

    def delete_session(self, session_id: str) -> bool:
        """Delete a single session. Returns True if deleted."""
        path = self._user_dir / _SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return False
        path.unlink()
        self._rebuild_session_index()
        return True

    def clear_all_sessions(self) -> None:
        """Delete all session records for this user."""
        sessions_dir = self._user_dir / _SESSIONS_DIR
        if sessions_dir.exists():
            import shutil
            shutil.rmtree(sessions_dir)
        sessions_dir.mkdir(parents=True, exist_ok=True)
        self._write_session_index({"sessions": []})

    # ── Memory management ──────────────────────────────────────────────

    def clear_all(self) -> None:
        """Clear all memory (profile + sessions) for this user."""
        self.clear_profile()
        self.clear_active_session()
        self.clear_all_sessions()
        logger.info(f"Cleared all interview memory for user {self._user_id}")

    def export_all(self) -> dict[str, Any]:
        """Export all memory for this user as a dict."""
        return {
            "user_id": self._user_id,
            "profile": self.read_profile().to_dict(),
            "active_session": (
                active.to_dict()
                if (active := self.read_active_session()) is not None
                else None
            ),
            "sessions": [
                self.read_session(s["session_id"]).to_dict()  # type: ignore[union-attr]
                for s in self.list_sessions(limit=1000)
                if s.get("session_id")
            ],
        }

    def get_recent_sessions(self, limit: int = 5) -> list[InterviewSession]:
        """Get the most recent N sessions with full data."""
        summaries = self.list_sessions(limit=limit)
        result: list[InterviewSession] = []
        for s in summaries:
            session_id = s.get("session_id", "")
            if session_id:
                session = self.read_session(session_id)
                if session:
                    result.append(session)
        return result

    # ── Internal helpers ───────────────────────────────────────────────

    def _read_session_index(self) -> dict[str, Any]:
        path = self._user_dir / _SESSIONS_INDEX
        if not path.exists():
            return {"sessions": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            return {"sessions": []}

    def _write_session_index(self, index: dict[str, Any]) -> None:
        path = self._user_dir / _SESSIONS_INDEX
        path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _update_session_index(self, session: InterviewSession) -> None:
        index = self._read_session_index()
        existing = [s for s in index["sessions"] if s.get("session_id") != session.session_id]
        existing.append({
            "session_id": session.session_id,
            "question_type": session.question_type,
            "difficulty": session.difficulty,
            "total_score": session.total_score,
            "completed_at": session.completed_at or datetime.now().astimezone().isoformat(),
        })
        index["sessions"] = existing
        self._write_session_index(index)

    def _rebuild_session_index(self) -> None:
        """Rebuild the session index from scratch from session files."""
        sessions_dir = self._user_dir / _SESSIONS_DIR
        entries: list[dict[str, Any]] = []
        if sessions_dir.exists():
            for f in sorted(sessions_dir.iterdir()):
                if f.suffix == ".json":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        entries.append({
                            "session_id": data.get("session_id", f.stem),
                            "question_type": data.get("question_type", ""),
                            "difficulty": data.get("difficulty", ""),
                            "total_score": data.get("total_score", 0.0),
                            "completed_at": data.get("completed_at", ""),
                        })
                    except (json.JSONDecodeError, KeyError):
                        continue
        self._write_session_index({"sessions": entries})


_INSTANCES: dict[str, InterviewMemoryService] = {}


def get_interview_memory_service(user_id: str = "default") -> InterviewMemoryService:
    """Get or create a InterviewMemoryService for the given user."""
    if user_id not in _INSTANCES:
        _INSTANCES[user_id] = InterviewMemoryService(user_id=user_id)
    return _INSTANCES[user_id]


def reset_interview_memory_instances() -> None:
    """Clear all cached instances (useful for testing)."""
    _INSTANCES.clear()


__all__ = [
    "InterviewMemoryService",
    "get_interview_memory_service",
    "reset_interview_memory_instances",
]
