"""User Session Manager — session tracking and access control.

Manages active user sessions for the dashboard/API, tracks
who is connected and what they're monitoring.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class UserSession:
    """An active user session."""
    session_id: str
    user_id: str
    user_name: str = ""
    role: str = "viewer"
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    ip_address: str = ""
    user_agent: str = ""
    # What the user is monitoring
    subscriptions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def idle_s(self) -> float:
        return time.time() - self.last_active

    def touch(self) -> None:
        self.last_active = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "role": self.role,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "idle_s": round(self.idle_s, 1),
            "subscriptions": self.subscriptions,
            "ip_address": self.ip_address,
        }


class SessionManager:
    """Manages active user sessions."""

    def __init__(self, session_timeout_s: float = 3600) -> None:
        self._sessions: dict[str, UserSession] = {}
        self._timeout_s = session_timeout_s

    def create_session(
        self,
        user_id: str,
        user_name: str = "",
        role: str = "viewer",
        ip_address: str = "",
        user_agent: str = "",
    ) -> UserSession:
        """Create a new session."""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = UserSession(
            session_id=session_id,
            user_id=user_id,
            user_name=user_name,
            role=role,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._sessions[session_id] = session
        _log.info("Session created: %s for %s", session_id, user_id)
        return session

    def get_session(self, session_id: str) -> UserSession | None:
        session = self._sessions.get(session_id)
        if session and session.idle_s > self._timeout_s:
            self.destroy_session(session_id)
            return None
        return session

    def touch_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session:
            session.touch()
            return True
        return False

    def destroy_session(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session:
            _log.info("Session destroyed: %s", session_id)
            return True
        return False

    def subscribe(self, session_id: str, topic: str) -> bool:
        """Subscribe a session to a monitoring topic."""
        session = self._sessions.get(session_id)
        if session and topic not in session.subscriptions:
            session.subscriptions.append(topic)
            return True
        return False

    def unsubscribe(self, session_id: str, topic: str) -> bool:
        session = self._sessions.get(session_id)
        if session and topic in session.subscriptions:
            session.subscriptions.remove(topic)
            return True
        return False

    def list_sessions(self, active_only: bool = True) -> list[dict[str, Any]]:
        sessions = list(self._sessions.values())
        if active_only:
            sessions = [s for s in sessions if s.idle_s <= self._timeout_s]
        return [s.to_dict() for s in sessions]

    def cleanup_expired(self) -> int:
        """Remove expired sessions."""
        expired = [
            sid for sid, s in self._sessions.items()
            if s.idle_s > self._timeout_s
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        return len(expired)

    def stats(self) -> dict[str, Any]:
        active = [s for s in self._sessions.values() if s.idle_s <= self._timeout_s]
        return {
            "total_sessions": len(self._sessions),
            "active_sessions": len(active),
            "by_role": self._count_by("role"),
        }

    def _count_by(self, attr: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self._sessions.values():
            val = getattr(s, attr, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts
