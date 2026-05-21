"""Tests for the security module (RBAC, taint tracking, output filter)."""

from more_core.security.rbac import RBACManager, Permission, Role, ROLE_ADMIN, ROLE_VIEWER
from more_core.security.taint import TaintTracker, TaintLabel, TaintedValue
from more_core.security.output_filter import OutputFilter, FilterRule


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
    f = OutputFilter()
    text = "Set PASSWORD=my_super_secret in env"
    result = f.filter(text)
    assert "my_super_secret" not in result


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
    f.add_rule(FilterRule(name="ssn", pattern=__import__("re").compile(r"\d{3}-\d{2}-\d{4}"), replacement="[SSN]"))
    result = f.filter("SSN is 123-45-6789")
    assert "123-45-6789" not in result
    assert "[SSN]" in result
