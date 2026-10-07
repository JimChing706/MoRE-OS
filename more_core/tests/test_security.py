"""Tests for the security module (RBAC, taint tracking, output filter)."""

from more_core.security.output_filter import FilterRule, OutputFilter
from more_core.security.rbac import (
    Permission,
    RBACManager,
    Role,
    UnifiedRBAC,
    require_permission,
    requires_permission,
    set_rbac_instance,
)
from more_core.security.taint import TaintedValue, TaintLabel, TaintTracker

# -- RBAC ------------------------------------------------------------------


def test_rbac_disabled_allows_all():
    mgr = RBACManager()
    assert not mgr.enabled
    assert mgr.check_permission("unknown_user", Permission.SYS_ADMIN)


def test_rbac_enabled_blocks_unauthorized():
    mgr = RBACManager()
    mgr.enable()
    assert not mgr.check_permission("user1", Permission.TASK_EXECUTE)


def test_rbac_assign_role_grants_permissions():
    mgr = RBACManager()
    mgr.enable()
    mgr.assign_role("user1", "viewer")
    assert mgr.check_permission("user1", Permission.TASK_VIEW)
    assert not mgr.check_permission("user1", Permission.TASK_EXECUTE)


def test_rbac_admin_has_all():
    mgr = RBACManager()
    mgr.enable()
    mgr.assign_role("admin1", "admin")
    assert mgr.check_permission("admin1", Permission.SYS_ADMIN)
    assert mgr.check_permission("admin1", Permission.TOOL_SHELL)


def test_rbac_revoke_role():
    mgr = RBACManager()
    mgr.enable()
    mgr.assign_role("u", "operator")
    assert mgr.check_permission("u", Permission.TASK_EXECUTE)
    mgr.revoke_role("u", "operator")
    assert not mgr.check_permission("u", Permission.TASK_EXECUTE)


def test_rbac_custom_role():
    mgr = RBACManager()
    mgr.enable()
    custom = Role(name="custom", permissions={Permission.HAND_VIEW, Permission.LLM_VIEW})
    mgr.add_role(custom)
    mgr.assign_role("u", "custom")
    assert mgr.check_permission("u", Permission.HAND_VIEW)
    assert not mgr.check_permission("u", Permission.HAND_ACTIVATE)


def test_rbac_get_user_permissions():
    mgr = RBACManager()
    mgr.assign_role("u", "viewer")
    mgr.assign_role("u", "agent")
    perms = mgr.get_user_permissions("u")
    assert Permission.TASK_VIEW in perms
    assert Permission.TOOL_PYTHON in perms


# -- UnifiedRBAC (new API) ------------------------------------------------


def test_unified_rbac_dev_mode_allows_all():
    """Without admin users configured, check() always returns True."""
    rbac = UnifiedRBAC()
    assert rbac.check("anyone", Permission.SYS_ADMIN)
    assert rbac.check("anyone", Permission.TOOL_SHELL)
    assert rbac.check("anyone", Permission.MEMORY_DELETE)


def test_unified_rbac_with_admin_users_blocks_unknown():
    """With admin users set, unknown users are blocked."""
    rbac = UnifiedRBAC(admin_users=["alice"])
    assert not rbac.check("bob", Permission.TASK_EXECUTE)
    assert rbac.check("alice", Permission.TASK_EXECUTE)


def test_unified_rbac_role_assignment():
    rbac = UnifiedRBAC(admin_users=["alice"])
    rbac.assign_role("bob", "viewer")
    assert rbac.check("bob", Permission.TASK_VIEW)
    assert not rbac.check("bob", Permission.TASK_EXECUTE)


def test_unified_rbac_check_raise():
    rbac = UnifiedRBAC(admin_users=["alice"])
    rbac.check_raise("alice", Permission.SYS_ADMIN)  # no error
    import pytest as _pytest

    with _pytest.raises(PermissionError, match="bob lacks permission"):
        rbac.check_raise("bob", Permission.TOOL_SHELL)


def test_unified_rbac_register_plugin_permission():
    rbac = UnifiedRBAC()
    perm = rbac.register_permission("game:play")
    assert perm.value == "game:play"
    assert "game:play" in rbac._extra_permissions


def test_unified_rbac_stats():
    rbac = UnifiedRBAC(admin_users=["alice"])
    rbac.assign_role("bob", "viewer")
    stats = rbac.stats()
    assert stats["admin_users"] == 1
    assert stats["total_roles"] >= 5  # built-in roles
    assert stats["total_users"] == 1


def test_unified_rbac_list_roles():
    rbac = UnifiedRBAC()
    roles = rbac.list_roles()
    names = [r["name"] for r in roles]
    assert "admin" in names
    assert "viewer" in names
    assert "operator" in names


# -- require_permission / requires_permission helpers ----------------------


async def test_require_permission_dependency_allows_when_no_rbac():
    """When no global RBAC is set, the dependency is a no-op."""
    set_rbac_instance(None)
    dep = require_permission(Permission.SYS_ADMIN)
    await dep("someone")  # should not raise


async def test_require_permission_dependency_blocks_unauthorized():
    rbac = UnifiedRBAC(admin_users=["alice"])
    set_rbac_instance(rbac)
    dep = require_permission(Permission.TOOL_SHELL)
    import pytest as _pytest

    with _pytest.raises(PermissionError):
        await dep("bob")
    set_rbac_instance(None)  # cleanup


async def test_requires_permission_decorator_pops_user_id():
    rbac = UnifiedRBAC(admin_users=["alice"])
    set_rbac_instance(rbac)

    @requires_permission(Permission.TOOL_FILE_READ)
    async def fake_handler(params):
        return params  # return remaining params after _user_id pop

    # alice has admin → all permissions
    result = await fake_handler({"_user_id": "alice", "path": "/tmp"})
    assert "_user_id" not in result
    assert result["path"] == "/tmp"

    import pytest as _pytest

    with _pytest.raises(PermissionError):
        await fake_handler({"_user_id": "bob", "path": "/tmp"})

    set_rbac_instance(None)  # cleanup


# -- Backward compat -------------------------------------------------------


def test_legacy_rbac_manager_still_works():
    """Deprecated RBACManager should preserve its original behavior."""
    mgr = RBACManager()
    # Legacy mode without enable(): allow all (disabled)
    assert mgr.check_permission("anyone", Permission.TOOL_SHELL)
    # Enable legacy mode: blocks unauthorized
    mgr.enable()
    assert not mgr.check_permission("unknown", Permission.TOOL_SHELL)
    # Assign a role to a user
    mgr.assign_role("bob", "operator")
    assert mgr.check_permission("bob", Permission.TASK_EXECUTE)


# -- Taint Tracking --------------------------------------------------------


def test_taint_clean_value_is_trusted():
    tv = TaintedValue(value="hello", labels=TaintLabel.CLEAN)
    assert tv.is_trusted


def test_taint_user_input_is_untrusted():
    tv = TaintedValue(value="<script>", labels=TaintLabel.USER_INPUT, source="chat")
    assert not tv.is_trusted


def test_taint_sanitized_becomes_trusted():
    tv = TaintedValue(value="safe", labels=TaintLabel.USER_INPUT)
    assert not tv.is_trusted
    sanitized = tv.sanitize("html_escape")
    assert sanitized.is_trusted
    assert sanitized.sanitized_by == "html_escape"


def test_taint_tracker_check():
    tracker = TaintTracker()
    tracker.track("cmd", "rm -rf /", TaintLabel.USER_INPUT, source="user_msg")
    assert not tracker.check("cmd", required_trust=True)
    assert len(tracker.get_violations()) == 1


def test_taint_tracker_sanitize():
    tracker = TaintTracker()
    tracker.track("path", "../etc/passwd", TaintLabel.USER_INPUT)
    tracker.sanitize("path", "path_normalize")
    assert tracker.check("path", required_trust=True)


def test_taint_tracker_untracked_is_ok():
    tracker = TaintTracker()
    assert tracker.check("nonexistent", required_trust=True)


# -- Output Filter ---------------------------------------------------------


def test_output_filter_redacts_api_key():
    f = OutputFilter()
    text = "Use key sk-abcdefghij1234567890abcdefghij for auth"
    result = f.filter(text)
    assert "sk-abcdefghij" not in result
    assert "[API_KEY_REDACTED]" in result


def test_output_filter_redacts_email():
    f = OutputFilter()
    text = "Contact admin@example.com for help"
    result = f.filter(text)
    assert "admin@example.com" not in result
    assert "[EMAIL_REDACTED]" in result


def test_output_filter_redacts_phone():
    f = OutputFilter()
    text = "Call 13812345678 for support"
    result = f.filter(text)
    assert "13812345678" not in result
    assert "[PHONE_REDACTED]" in result


def test_output_filter_redacts_env_secret():
    """真密钥字面量仍然脱敏（长值 / 带引号两种形态）。"""
    f = OutputFilter()
    for text in (
        "Set PASSWORD=my_super_secret_value_123 in env",
        'PASSWORD="my_super_secret"',
        'API_KEY = "sk-live-abcdef0123456789"',
    ):
        assert f.filter(text) != text, text


def test_output_filter_preserves_python_keyword_arguments():
    """回归 F-01：脱敏规则不得破坏生成代码里的 key=/token= 形参。"""
    f = OutputFilter()
    for text in (
        "sorted(items, key=lambda x: x[0])",
        "def f(key=1, token=None): pass",
        "redis.set(key=user_id, value=data)",
        "token = refresh_token",
    ):
        assert f.filter(text) == text, text


def test_output_filter_scan():
    f = OutputFilter()
    text = "Keys: sk-xxxxxxxxxxxxxxxxxxxx and admin@foo.com"
    findings = f.scan(text)
    rules_found = [f["rule"] for f in findings]
    assert "api_key" in rules_found
    assert "email" in rules_found


def test_output_filter_stats():
    f = OutputFilter()
    f.filter("token sk-aaaabbbbccccddddeeee1234 here")
    stats = f.stats()
    assert stats["total_filtered"] >= 1
    assert "api_key" in stats["by_rule"]


def test_output_filter_custom_rule():
    f = OutputFilter(rules=[])
    f.add_rule(
        FilterRule(
            name="ssn", pattern=__import__("re").compile(r"\d{3}-\d{2}-\d{4}"), replacement="[SSN]"
        )
    )
    result = f.filter("SSN is 123-45-6789")
    assert "123-45-6789" not in result
    assert "[SSN]" in result
