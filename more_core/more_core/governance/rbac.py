"""Role-Based Access Control (RBAC) for MoRE OS."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Set

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """System permissions."""
    TASK_CREATE = "task:create"
    TASK_READ = "task:read"
    TASK_EXECUTE = "task:execute"
    TASK_DELETE = "task:delete"
    PLUGIN_INSTALL = "plugin:install"
    PLUGIN_UNINSTALL = "plugin:uninstall"
    PLUGIN_CONFIGURE = "plugin:configure"
    LLM_CONFIGURE = "llm:configure"
    LLM_VIEW_KEYS = "llm:view_keys"
    SYSTEM_CONFIGURE = "system:configure"
    SYSTEM_VIEW_LOGS = "system:view_logs"
    SYSTEM_AUDIT = "system:audit"
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    MEMORY_DELETE = "memory:delete"
    EVOLUTION_READ = "evolution:read"
    EVOLUTION_WRITE = "evolution:write"
    EVOLUTION_EXECUTE = "evolution:execute"


class Role(Enum):
    """System roles."""
    ADMIN = "admin"
    OPERATOR = "operator"
    DEVELOPER = "developer"
    USER = "user"
    GUEST = "guest"


ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_EXECUTE, Permission.TASK_DELETE,
        Permission.PLUGIN_INSTALL, Permission.PLUGIN_UNINSTALL, Permission.PLUGIN_CONFIGURE,
        Permission.LLM_CONFIGURE, Permission.LLM_VIEW_KEYS,
        Permission.SYSTEM_CONFIGURE, Permission.SYSTEM_VIEW_LOGS, Permission.SYSTEM_AUDIT,
        Permission.MEMORY_READ, Permission.MEMORY_WRITE, Permission.MEMORY_DELETE,
        Permission.EVOLUTION_READ, Permission.EVOLUTION_WRITE, Permission.EVOLUTION_EXECUTE,
    },
    Role.OPERATOR: {
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_EXECUTE,
        Permission.PLUGIN_CONFIGURE,
        Permission.LLM_CONFIGURE,
        Permission.SYSTEM_VIEW_LOGS,
        Permission.MEMORY_READ, Permission.MEMORY_WRITE,
        Permission.EVOLUTION_READ,
    },
    Role.DEVELOPER: {
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_EXECUTE,
        Permission.PLUGIN_INSTALL, Permission.PLUGIN_CONFIGURE,
        Permission.LLM_CONFIGURE,
        Permission.MEMORY_READ, Permission.MEMORY_WRITE,
        Permission.EVOLUTION_READ, Permission.EVOLUTION_WRITE,
    },
    Role.USER: {
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_EXECUTE,
        Permission.MEMORY_READ, Permission.MEMORY_WRITE,
        Permission.EVOLUTION_READ,
    },
    Role.GUEST: {
        Permission.TASK_READ,
        Permission.MEMORY_READ,
    },
}


@dataclass
class User:
    """User entity."""
    id: str
    name: str
    role: Role
    permissions: Set[Permission] = field(default_factory=set)
    
    def __post_init__(self):
        if not self.permissions:
            self.permissions = ROLE_PERMISSIONS.get(self.role, set())


@dataclass
class RBACPolicy:
    """RBAC Policy enforcement."""
    users: dict[str, User] = field(default_factory=dict)
    
    def add_user(self, user: User) -> None:
        """Add a user to the policy."""
        self.users[user.id] = user
    
    def remove_user(self, user_id: str) -> None:
        """Remove a user from the policy."""
        self.users.pop(user_id, None)
    
    def get_user(self, user_id: str) -> User | None:
        """Get a user by ID."""
        return self.users.get(user_id)
    
    def has_permission(self, user_id: str, permission: Permission) -> bool:
        """Check if a user has a specific permission."""
        user = self.users.get(user_id)
        if not user:
            return False
        return permission in user.permissions
    
    def check_permission(self, user_id: str, permission: Permission) -> None:
        """Check permission and raise if denied."""
        if not self.has_permission(user_id, permission):
            raise PermissionError(f"User {user_id} lacks permission: {permission.value}")
    
    def grant_permission(self, user_id: str, permission: Permission) -> None:
        """Grant an additional permission to a user."""
        user = self.users.get(user_id)
        if user:
            user.permissions.add(permission)
    
    def revoke_permission(self, user_id: str, permission: Permission) -> None:
        """Revoke a permission from a user."""
        user = self.users.get(user_id)
        if user:
            user.permissions.discard(permission)


def create_default_policy() -> RBACPolicy:
    """Create a default RBAC policy with default users."""
    policy = RBACPolicy()
    policy.add_user(User(id="admin", name="Administrator", role=Role.ADMIN))
    policy.add_user(User(id="operator", name="Operator", role=Role.OPERATOR))
    policy.add_user(User(id="developer", name="Developer", role=Role.DEVELOPER))
    policy.add_user(User(id="user", name="User", role=Role.USER))
    policy.add_user(User(id="guest", name="Guest", role=Role.GUEST))
    return policy