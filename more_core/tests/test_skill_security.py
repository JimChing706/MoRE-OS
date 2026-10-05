"""技能安全面回归（SSRF 防护等）。"""

from __future__ import annotations

import pytest

from more_core.skills import APICallSkill, WebBrowseSkill


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",   # 云元数据
        "http://127.0.0.1:8011/api/v1/health",        # 回环
        "http://localhost:11434/api/tags",            # 私有主机名
        "http://10.0.0.5/internal",                   # 私网
        "file:///etc/passwd",                          # 非 http(s)
    ],
)
async def test_api_call_blocks_ssrf(url):
    """api.call 必须做 SSRF 校验（此前完全缺失，可打内网/云元数据）。"""
    result = await APICallSkill().execute({"url": url})
    assert result.success is False
    assert result.error, "必须给出拒绝原因"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["http://169.254.169.254/", "http://127.0.0.1/", "http://localhost/"],
)
async def test_web_browse_blocks_ssrf(url):
    result = await WebBrowseSkill().execute({"url": url})
    assert result.success is False


def test_ssrf_guard_allows_public_urls():
    from more_core.security.ssrf import validate_http_url

    for url in ("https://example.com/x", "http://8.8.8.8/"):
        assert validate_http_url(url) == url


# ---------------------------------------------------------------------------
# R-1：code.execute 必须在 OS 级安全沙箱内执行
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_execute_blocks_dangerous_python():
    from more_core.skills import CodeExecutionSkill

    r = await CodeExecutionSkill().execute(
        {"code": "import os; os.system('echo pwned')", "language": "python", "timeout": 10}
    )
    assert r.success is False
    assert "Blocked" in (r.error or "")
    assert r.metadata.get("sandboxed") is True


@pytest.mark.asyncio
async def test_code_execute_blocks_destructive_bash():
    from more_core.skills import CodeExecutionSkill

    r = await CodeExecutionSkill().execute({"code": "rm -rf /", "language": "bash", "timeout": 10})
    assert r.success is False


@pytest.mark.asyncio
async def test_code_execute_subprocess_is_sandboxed():
    from more_core.skills import CodeExecutionSkill

    r = await CodeExecutionSkill().execute(
        {"code": "import subprocess; subprocess.run(['echo','x'])",
         "language": "python", "timeout": 10}
    )
    assert r.success is False
    assert "subprocess" in (r.error or "")


@pytest.mark.asyncio
async def test_code_execute_allows_safe_code_all_languages():
    from more_core.skills import CodeExecutionSkill

    skill = CodeExecutionSkill()
    cases = [
        ("python", "print(6 * 7)", "42"),
        ("javascript", "console.log(6 * 7)", "42"),
        ("bash", "echo $((6 * 7))", "42"),
    ]
    for lang, code, needle in cases:
        r = await skill.execute({"code": code, "language": lang, "timeout": 10})
        assert r.success is True, (lang, r.error)
        assert needle in str(r.output), (lang, r.output)
        assert r.metadata.get("sandboxed") is True


def test_create_secure_sandbox_accepts_positional_security_level():
    """容错回归：位置传安全级别曾导致 AttributeError('str' has no 'timeout_s')。"""
    from more_core.sandbox.secure_sandbox import SecurityLevel, create_secure_sandbox

    sbx = create_secure_sandbox("strict")
    assert sbx.config.security_level is SecurityLevel.STRICT
