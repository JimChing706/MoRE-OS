"""SSRF guard — block outbound HTTP to private/loopback/link-local hosts.

Any tool that fetches user-supplied URLs (web browse, browser hand, etc.)
must call :func:`validate_http_url` before issuing the request so an agent
cannot probe or tamper with the local network, host services, or cloud
metadata endpoints.

The guard blocks literal private IPs and well-known private hostnames
(localhost, *.local, *.internal). DNS resolution is intentionally NOT used
to classify hosts: resolvers behind VPNs/proxies/NAT64 overlay networks
routinely answer public names with private addresses, so a DNS-based check
would produce false positives in exactly those deployments.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# RFC 1918 + loopback + link-local + unspecified + CGNAT blocks
_PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local incl. AWS metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # unique-local
    ipaddress.ip_network("fe80::/10"),  # link-local
    ipaddress.ip_network("::/128"),  # unspecified
)


_PRIVATE_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
)


def is_private_address(ip: str) -> bool:
    """Return True when *ip* is loopback, private, link-local, or reserved."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # non-IP → treat as unsafe rather than guess
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or any(addr in net for net in _PRIVATE_NETWORKS)
    )


def is_private_host(host: str) -> bool:
    """Return True for well-known private hostnames (no DNS involved)."""
    lowered = host.lower()
    if lowered in ("localhost", "localhost.localdomain"):
        return True
    return any(lowered.endswith(suffix) for suffix in _PRIVATE_HOST_SUFFIXES)


def validate_http_url(url: str) -> str:
    """Validate *url* for outbound fetching.

    Raises :class:`ValueError` for non-http(s) schemes, missing hosts, or
    URLs whose literal host is a private/loopback/link-local address or a
    well-known private hostname. Returns the url unchanged on success.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL is missing a host")
    if is_private_host(host):
        raise ValueError(f"URL host is a private hostname: {host}")
    try:
        ipaddress.ip_address(host)  # literal IP → classify it
    except ValueError:
        return url  # hostname → not classified without DNS
    if is_private_address(host):
        raise ValueError(f"URL host is a private/loopback address: {host}")
    return url
