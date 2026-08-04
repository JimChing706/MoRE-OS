"""Tests for SSRF guard and its integration in URL-fetching tools."""

from __future__ import annotations

import pytest

from more_core.security.ssrf import is_private_address, validate_http_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost/health",
        "http://10.0.0.5/secret",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
        "http://[fc00::1]/x",
        "http://db.internal/x",
        "http://printer.local/x",
    ],
)
def test_validate_http_url_rejects_private(url: str) -> None:
    with pytest.raises(ValueError, match=r"private/loopback|private hostname"):
        validate_http_url(url)


def test_validate_http_url_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        validate_http_url("ftp://example.com/file")


def test_validate_http_url_rejects_missing_host() -> None:
    with pytest.raises(ValueError, match="host"):
        validate_http_url("http://")


def test_validate_http_url_accepts_public_url() -> None:
    assert validate_http_url("https://example.com/path") == "https://example.com/path"


def test_is_private_address_rejects_public_ip() -> None:
    assert is_private_address("8.8.8.8") is False
    assert is_private_address("1.1.1.1") is False


def test_is_private_address_accepts_private_ips() -> None:
    assert is_private_address("127.0.0.1") is True
    assert is_private_address("10.1.2.3") is True
    assert is_private_address("192.168.0.1") is True
    assert is_private_address("169.254.169.254") is True
    assert is_private_address("::1") is True


@pytest.mark.asyncio
async def test_web_browse_blocks_internal_url() -> None:
    from more_core.skills.web_skills import WebBrowseSkill

    skill = WebBrowseSkill()
    result = await skill.execute({"url": "http://127.0.0.1:8011/api/v1/health"})
    assert result.success is False
    assert "private/loopback" in str(result.error)


@pytest.mark.asyncio
async def test_browser_hand_blocks_internal_url() -> None:
    from more_core.hands.browser_hand import BrowserHand

    hand = BrowserHand()
    result = await hand._navigate("http://169.254.169.254/latest/meta-data", {})
    assert result.success is False
    assert "private/loopback" in str(result.error)
