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
