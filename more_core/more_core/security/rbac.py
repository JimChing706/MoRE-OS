"""Role-Based Access Control (RBAC) for MoRE OS.

Reference: OpenFang RBAC system.
Provides fine-grained permission control for API endpoints,
tools, and Hands activation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class Permission(Enum):
    """System permissions."""
    # Task permissions
    TASK_EXECUTE = "task.execute"
    TASK_VIEW = "task.view"
    # Hand permissions
    HAND_ACTIVATE = "hand.activate"
    HAND_DEACTIVATE = "hand.deactivate"
    HAND_RUN = "hand.run"
    HAND_VIEW = "hand.view"
    # LLM permissions
    LLM_UPDATE = "llm.update"
    LLM_VIEW = "llm.view"
    # Tool permissions
    TOOL_SHELL = "tool.shell"
    TOOL_FILE_WRITE = "tool.file_write"
    TOOL_FILE_READ = "tool.file_read"
    TOOL_PYTHON = "tool.python"
    # Governance
    GOV_RESOLVE = "gov.resolve"
    GOV_VIEW = "gov.view"
    # System
    SYS_CONFIG = "sys.config"
    SYS_ADMIN = "sys.admin"
    # Channel
    CHANNEL_MANAGE = "channel.manage"
    CHANNEL_VIEW = "channel.view"


@dataclass
class Role:
    """A named role with a set of permissions."""
    name: str
    description: str = ""
    permissions: set[Permission] = field(default_factory=set)

    def has_permission(self, perm: Permission) -> bool:
        return perm in self.permissions


# Pre-defined roles
ROLE_ADMIN = Role(
    name="admin",
    description="Full system access",
    permissions=set(Permission),
)

ROLE_OPERATOR = Role(
    name="operator",
    description="Operational access (execute tasks, manage hands, view all)",
    permissions={
        Permission.TASK_EXECUTE, Permission.TASK_VIEW,
        Permission.HAND_ACTIVATE, Permission.HAND_DEACTIVATE,
        Permission.HAND_RUN, Permission.HAND_VIEW,
        Permission.LLM_UPDATE, Permission.LLM_VIEW,
        Permission.TOOL_FILE_READ, Permission.TOOL_PYTHON,
        Permission.GOV_VIEW, Permission.CHANNEL_VIEW,
    },
)

ROLE_VIEWER = Role(
    name="viewer",
    description="Read-only access",
    permissions={
        Permission.TASK_VIEW, Permission.HAND_VIEW,
        Permission.LLM_VIEW, Permission.GOV_VIEW,
        Permission.CHANNEL_VIEW,
    },
)

ROLE_AGENT = Role(
    name="agent",
    description="AI agent role (limited tool access)",
    permissions={
        Permission.TASK_EXECUTE, Permission.TASK_VIEW,
        Permission.HAND_VIEW, Permission.LLM_VIEW,
        Permission.TOOL_FILE_READ, Permission.TOOL_PYTHON,
    },
)


class RBACManager:
    """Manages roles and user-role assignments."""

    def __init__(self) -> None:
        self._roles: dict[str, Role] = {
            "admin": ROLE_ADMIN,
            "operator": ROLE_OPERATOR,
            "viewer": ROLE_VIEWER,
            "agent": ROLE_AGENT,
        }
        self._user_roles: dict[str, list[str]] = {}
        # Default: no RBAC enforcement (dev mode)
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        _log.info("RBAC enforcement enabled")

    def disable(self) -> None:
        self._enabled = False
        _log.info("RBAC enforcement disabled")

    def add_role(self, role: Role) -> None:
        self._roles[role.name] = role

    def assign_role(self, user_id: str, role_name: str) -> bool:
        if role_name not in self._roles:
            return False
        self._user_roles.setdefault(user_id, [])
        if role_name not in self._user_roles[user_id]:
            self._user_roles[user_id].append(role_name)
        return True

    def revoke_role(self, user_id: str, role_name: str) -> bool:
        roles = self._user_roles.get(user_id, [])
        if role_name in roles:
            roles.remove(role_name)
            return True
        return False

    def check_permission(self, user_id: str, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        if not self._enabled:
            return True  # RBAC disabled = allow all
        roles = self._user_roles.get(user_id, [])
        for role_name in roles:
            role = self._roles.get(role_name)
            if role and role.has_permission(permission):
                return True
        return False

    def get_user_permissions(self, user_id: str) -> set[Permission]:
        """Get all permissions for a user across all assigned roles."""
        perms: set[Permission] = set()
        for role_name in self._user_roles.get(user_id, []):
            role = self._roles.get(role_name)
            if role:
                perms |= role.permissions
        return perms

    def list_roles(self) -> list[dict[str, Any]]:
        return [
            {
                "name": r.name,
                "description": r.description,
                "permissions": [p.value for p in r.permissions],
            }
            for r in self._roles.values()
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "total_roles": len(self._roles),
            "total_users": len(self._user_roles),
            "roles": list(self._roles.keys()),
        }
