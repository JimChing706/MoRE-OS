"""FastAPI auth dependencies shared by the modular routers.

``require_api_key`` lives in :mod:`more_core.api.server` and is injected into
every router factory.  Scope enforcement is orthogonal to it and needs to be
importable *from* the routers, so it lives here to avoid an import cycle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

try:
    from fastapi import HTTPException, Request
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "QNMing MoRE OS API requires the 'api' extra: pip install 'qnming-more-os[api]'"
    ) from exc

from ..security.api_key_store import WILDCARD_SCOPE

__all__ = ["require_scope"]


def require_scope(scope: str) -> Callable[[Request], Awaitable[None]]:
    """Return a dependency asserting the presented API key carries *scope*.

    Keys issued with ``*`` (the legacy ``MORE_API_KEY`` and admin keys) pass
    every scope check.  When authentication is disabled entirely — no
    ``MORE_API_KEY`` and no registered keys — the dependency is a no-op so the
    documented dev-mode contract is preserved.
    """

    async def _checker(request: Request) -> None:
        scopes = getattr(request.state, "api_key_scopes", None)
        if scopes is None:
            return
        if WILDCARD_SCOPE in scopes or scope in scopes:
            return
        raise HTTPException(
            status_code=403,
            detail=f"API key lacks required scope {scope!r}",
        )

    return _checker
