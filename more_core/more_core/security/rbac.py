"""Unified Role-Based Access Control (RBAC) for MoRE OS.

Merges ``security/rbac.py`` (dot-notation, tool-level) and
``governance/rbac.py`` (colon-notation, resource-level) into one
enumeration with a single enforcement API.

Usage::

    # FastAPI endpoint
    @router.get("/admin", dependencies=[Depends(require_permission(Permission.SYS_ADMIN))])

    # Tool handler
    @requires_permission(Permission.TOOL_SHELL)
    async def my_tool(params): ...

    # Programmatic
    rbac = UnifiedRBAC()
    rbac.assign_role("alice", "admin")
    assert rbac.check("alice", Permission.TASK_EXECUTE)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)

_rbac_instance: UnifiedRBAC | None = None


def set_rbac_instance(rbac: UnifiedRBAC | None) -> None:
    global _rbac_instance
    _rbac_instance = rbac


def get_rbac() -> UnifiedRBAC | None:
    return _rbac_instance


class Permission(str, Enum):
    """Unified system permissions across all domains.

    Uses colon-separated namespaces for extensibility.
    Plugins can call ``UnifiedRBAC.register_permission()`` to add new ones.
    """

    @classmethod
    def _missing_(cls, value: object) -> Permission | None:
        if isinstance(value, str):
            obj = str.__new__(cls, value)
            obj._name_ = value
            obj._value_ = value
            return obj
        return None

    # -- task domain --
    TASK_EXECUTE = "task:execute"
    TASK_VIEW = "task:view"
    TASK_DELETE = "task:delete"

    # -- hand domain --
    HAND_ACTIVATE = "hand:activate"
    HAND_DEACTIVATE = "hand:deactivate"
    HAND_RUN = "hand:run"
    HAND_VIEW = "hand:view"

    # -- llm domain --
    LLM_UPDATE = "llm:update"
    LLM_VIEW = "llm:view"
    LLM_VIEW_KEYS = "llm:view_keys"

    # -- tool domain --
    TOOL_SHELL = "tool:shell"
    TOOL_FILE_WRITE = "tool:file_write"
    TOOL_FILE_READ = "tool:file_read"
    TOOL_PYTHON = "tool:python"

    # -- memory domain --
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    MEMORY_DELETE = "memory:delete"

    # -- evolution domain --
    EVOLUTION_READ = "evolution:read"
    EVOLUTION_WRITE = "evolution:write"
    EVOLUTION_EXECUTE = "evolution:execute"

    # -- governance domain --
    GOV_RESOLVE = "gov:resolve"
    GOV_VIEW = "gov:view"

    # -- system domain --
    SYS_CONFIG = "sys:config"
    SYS_ADMIN = "sys:admin"
    SYS_AUDIT = "sys:audit"

    # -- channel domain --
    CHANNEL_MANAGE = "channel:manage"
    CHANNEL_VIEW = "channel:view"


@dataclass
class Role:
    name: str
    description: str = ""
    permissions: set[Permission] = field(default_factory=set)


# ---- built-in roles ----
ROLE_ADMIN = Role(
    name="admin",
    description="Full system access",
    permissions=set(Permission),
)

ROLE_OPERATOR = Role(
    name="operator",
    description="Operational access",
    permissions={
        Permission.TASK_EXECUTE,
        Permission.TASK_VIEW,
        Permission.TASK_DELETE,
        Permission.HAND_ACTIVATE,
        Permission.HAND_DEACTIVATE,
        Permission.HAND_RUN,
        Permission.HAND_VIEW,
        Permission.LLM_UPDATE,
        Permission.LLM_VIEW,
        Permission.TOOL_FILE_READ,
        Permission.TOOL_PYTHON,
        Permission.MEMORY_READ,
        Permission.MEMORY_WRITE,
        Permission.EVOLUTION_READ,
        Permission.EVOLUTION_WRITE,
        Permission.EVOLUTION_EXECUTE,
        Permission.GOV_VIEW,
        Permission.CHANNEL_VIEW,
    },
)

ROLE_VIEWER = Role(
    name="viewer",
    description="Read-only access",
    permissions={
        Permission.TASK_VIEW,
        Permission.HAND_VIEW,
        Permission.LLM_VIEW,
        Permission.GOV_VIEW,
        Permission.CHANNEL_VIEW,
        Permission.MEMORY_READ,
        Permission.EVOLUTION_READ,
    },
)

ROLE_AGENT = Role(
    name="agent",
    description="AI agent role (limited tool access)",
    permissions={
        Permission.TASK_EXECUTE,
        Permission.TASK_VIEW,
        Permission.HAND_VIEW,
        Permission.LLM_VIEW,
        Permission.TOOL_FILE_READ,
        Permission.TOOL_PYTHON,
        Permission.MEMORY_READ,
    },
)

ROLE_DEVELOPER = Role(
    name="developer",
    description="Development access",
    permissions={
        Permission.TASK_EXECUTE,
        Permission.TASK_VIEW,
        Permission.TASK_DELETE,
        Permission.HAND_VIEW,
        Permission.HAND_ACTIVATE,
        Permission.HAND_DEACTIVATE,
        Permission.LLM_UPDATE,
        Permission.LLM_VIEW,
        Permission.LLM_VIEW_KEYS,
        Permission.TOOL_FILE_READ,
        Permission.TOOL_FILE_WRITE,
        Permission.TOOL_PYTHON,
        Permission.TOOL_SHELL,
        Permission.MEMORY_READ,
        Permission.MEMORY_WRITE,
        Permission.MEMORY_DELETE,
        Permission.EVOLUTION_READ,
        Permission.EVOLUTION_WRITE,
        Permission.EVOLUTION_EXECUTE,
        Permission.GOV_VIEW,
        Permission.CHANNEL_VIEW,
    },
)

_ROLE_DEFAULTS: dict[str, Role] = {
    "admin": ROLE_ADMIN,
    "operator": ROLE_OPERATOR,
    "viewer": ROLE_VIEWER,
    "agent": ROLE_AGENT,
    "developer": ROLE_DEVELOPER,
}


class UnifiedRBAC:
    """Central RBAC enforcement — single source of truth.

    Design decisions:
    * No ``enable/disable`` switch — if ``admin_users`` env var is set,
      only listed users have access; otherwise every user is allowed.
    * Extensible via ``register_permission()`` (plugin-facing).
    * ``user_id`` is resolved from the auth token at the FastAPI layer.
    """

    def __init__(self, admin_users: list[str] | None = None) -> None:
        self._roles: dict[str, Role] = dict(_ROLE_DEFAULTS)
        self._user_roles: dict[str, list[str]] = {}
        self._admin_users: set[str] = set(admin_users or [])
        self._extra_permissions: dict[str, Permission] = {}

    # -- permission registry (plugin extensibility) -------------------------

    def register_permission(self, name: str, perm: Permission | None = None) -> Permission:
        """Register a dynamic permission for plugins.

        If ``perm`` is given it is stored under *name*; otherwise a new
        ``Permission`` member is created on the fly.
        """
        if perm is not None:
            self._extra_permissions[name] = perm
            return perm
        # Create an ad-hoc permission (string-based).
        p = Permission(name)
        self._extra_permissions[name] = p
        return p

    # -- role management ----------------------------------------------------

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

    # -- permission checking ------------------------------------------------

    def _is_admin(self, user_id: str) -> bool:
        if not self._admin_users:
            return False
        if user_id in self._admin_users:
            return True
        return any(rn == "admin" for rn in self._user_roles.get(user_id, []))

    def check(self, user_id: str, permission: Permission) -> bool:
        # If no admin users are configured we are in dev mode.  Historically
        # this allowed everyone; set MORE_RBAC_STRICT=1 to deny instead
        # (RESIDUAL_RISKS R-03 mitigation).
        if not self._admin_users:
            if os.getenv("MORE_RBAC_STRICT", "0") == "1":
                _log.warning(
                    "RBAC strict mode: denying %s for %s (no admin_users configured)",
                    permission.value,
                    user_id,
                )
                return False
            return True
        if user_id in self._admin_users or self._is_admin(user_id):
            return True
        for rn in self._user_roles.get(user_id, []):
            role = self._roles.get(rn)
            if role and permission in role.permissions:
                return True
        return False

    def check_raise(self, user_id: str, permission: Permission) -> None:
        if not self.check(user_id, permission):
            raise PermissionError(f"user {user_id} lacks permission {permission.value}")

    def get_user_permissions(self, user_id: str) -> set[Permission]:
        result: set[Permission] = set()
        for rn in self._user_roles.get(user_id, []):
            role = self._roles.get(rn)
            if role:
                result |= role.permissions
        return result

    # -- backward compat ----------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self._admin_users)

    # -- query --------------------------------------------------------------

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
            "admin_users": len(self._admin_users),
            "total_roles": len(self._roles),
            "total_users": len(self._user_roles),
            "extra_permissions": list(self._extra_permissions.keys()),
        }


# ---- FastAPI dependency helper ----


def _header_default() -> Any:
    """FastAPI ``Header`` sentinel or ``None`` when the api extra is absent.

    Evaluated when ``require_permission(...)`` is called, so the optional
    ``fastapi`` dependency is never required at import time.
    """
    try:
        from fastapi import Header

        return Header(None, alias="X-User-Id")
    except ImportError:  # pragma: no cover — api extra not installed
        return None


def require_permission(permission: Permission) -> Callable[..., Awaitable[None]]:
    """Return a FastAPI dependency callable that checks *permission*.

    The caller identity is read from the ``X-User-Id`` request header,
    defaulting to ``"anonymous"``.

    Usage::

        @router.get("/admin", dependencies=[Depends(require_permission(Permission.SYS_ADMIN))])
    """

    async def _checker(
        x_user_id: str | None = _header_default(),
    ) -> None:
        rbac = get_rbac()
        if rbac is None:
            return
        rbac.check_raise(x_user_id or "anonymous", permission)

    return _checker


# ---- tool handler decorator ----


def requires_permission(
    permission: Permission,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for tool handlers that need RBAC checks.

    Usage::

        @requires_permission(Permission.TOOL_SHELL)
        async def shell_tool(params: dict) -> ToolResult: ...

    The *user_id* is extracted from ``params.get("_user_id", "anonymous")``
    so the caller (L0 execution) must inject it before dispatch.
    """

    def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapper(params: dict[str, Any]) -> Any:
            user_id = params.pop("_user_id", "anonymous")
            rbac = get_rbac()
            if rbac is not None:
                rbac.check_raise(user_id, permission)
            return await handler(params)

        return wrapper

    return decorator


# ---- backward-compatible aliases (deprecated) ----

from warnings import warn as _warn

_RBACManager_deprecated: bool = False


class RBACManager(UnifiedRBAC):
    """Deprecated alias for :class:`UnifiedRBAC`.

    Retained for backward compatibility; scheduled for removal in v0.7.0.
    """

    _legacy_enabled: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        global _RBACManager_deprecated
        if not _RBACManager_deprecated:
            _warn(
                "RBACManager is deprecated; use UnifiedRBAC instead",
                DeprecationWarning,
                stacklevel=2,
            )
            _RBACManager_deprecated = True
        super().__init__(*args, **kwargs)

    def enable(self) -> None:
        self._legacy_enabled = True

    def disable(self) -> None:
        self._legacy_enabled = False

    @property
    def enabled(self) -> bool:
        return self._legacy_enabled or bool(self._admin_users)

    def check_permission(self, user_id: str, permission: Permission) -> bool:
        if not self._legacy_enabled and not self._admin_users:
            return True  # legacy disabled — allow all
        if self._legacy_enabled and not self._admin_users:
            # Legacy enabled without admin users: role-based only
            for rn in self._user_roles.get(user_id, []):
                role = self._roles.get(rn)
                if role and permission in role.permissions:
                    return True
            return False
        return self.check(user_id, permission)
