"""QNMing MoRE OS — FastAPI platform API.

Keeps the surface minimal and *domain-neutral*: any industry verb goes
through plugins, never through hard-coded endpoints.

Endpoints are organised into modular routers under ``api/routers/``.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "QNMing MoRE OS API requires the 'api' extra: pip install 'qnming-more-os[api]'"
    ) from exc

from ..runtime.orchestrator import MoRECore
from ..security.api_key_store import WILDCARD_SCOPE
from ..security.principal import principal_from_api_key_id, set_principal
from ..version import __version__

if TYPE_CHECKING:  # pragma: no cover
    from ..security.api_key_store import APIKeyStore

from .routers import (
    create_admin_api_key_router,
    create_a2a_router,
    create_channels_router,
    create_commands_router,
    create_cron_router,
    create_deployments_router,
    create_delivery_router,
    create_deliberate_router,
    create_hands_router,
    create_health_router,
    create_hotreload_router,
    create_import_task_router,
    create_llm_router,
    create_mcp_router,
    create_monitor_router,
    create_outputs_router,
    create_requirements_router,
    create_security_router,
    create_sessions_router,
    create_skills_router,
    create_tasks_router,
    create_workflows_router,
    create_zen_router,
)

_log = logging.getLogger(__name__)

#: Minimum accepted length for MORE_API_KEY. Anything shorter is guessable.
API_KEY_MIN_LENGTH = 16

#: Recommended key prefix, checked in strict mode only (advisory elsewhere).
API_KEY_PREFIX = "sk-more-os-"


class APIKeyConfigError(RuntimeError):
    """Raised at startup when MORE_API_KEY is missing or malformed.

    Only raised when strict mode is on (``MORE_REQUIRE_API_KEY=1`` or
    ``require=True``).  Without it the platform keeps its dev-mode contract:
    an unset key means "run unauthenticated", and only a loud warning is
    emitted.
    """


def validate_api_key(*, require: bool | None = None) -> str:
    """Validate ``MORE_API_KEY`` and return it (``""`` when auth is disabled).

    Args:
        require: Force strict mode on/off.  ``None`` (default) defers to the
            ``MORE_REQUIRE_API_KEY`` environment variable.

    Returns:
        The stripped key, or an empty string when no key is configured.

    Raises:
        APIKeyConfigError: In strict mode, when the key is absent, too short,
            or (strict mode) missing the recommended prefix.
    """
    if require is None:
        require = os.getenv("MORE_REQUIRE_API_KEY", "0") == "1"

    key = (os.getenv("MORE_API_KEY") or "").strip()

    if not key:
        if require:
            raise APIKeyConfigError(
                "MORE_API_KEY is required but not set. Strict mode "
                "(MORE_REQUIRE_API_KEY=1) refuses to start the API "
                "unauthenticated. Set MORE_API_KEY in more_core/.env, or "
                "export MORE_API_KEY=<key> before starting. Use "
                "MORE_REQUIRE_API_KEY=0 to opt out of this check."
            )
        _log.warning(
            "MORE_API_KEY is not set — API is running UNAUTHENTICATED. "
            "Set MORE_API_KEY to enable Bearer-token auth."
        )
        return ""

    if len(key) < API_KEY_MIN_LENGTH:
        message = (
            f"MORE_API_KEY is too short: {len(key)} characters, "
            f"minimum {API_KEY_MIN_LENGTH}. Generate a longer key — see "
            "docs/API_KEY.md."
        )
        if require:
            raise APIKeyConfigError(message)
        _log.warning("%s", message)

    if require and not key.startswith(API_KEY_PREFIX):
        raise APIKeyConfigError(
            f"MORE_API_KEY must start with {API_KEY_PREFIX!r} in strict "
            f"mode, got {key[: len(API_KEY_PREFIX)]!r}…."
        )

    return key


def _key_store() -> "APIKeyStore | None":
    """Return the process API-key store, or ``None`` when storage is unavailable."""
    try:
        from ..security.api_key_store import get_default_store

        return get_default_store()
    except Exception as exc:  # pragma: no cover - defensive: never block boot
        _log.warning("API key store unavailable, falling back to MORE_API_KEY: %s", exc)
        return None


def _has_registered_keys(store: "APIKeyStore | None") -> bool:
    if store is None:
        return False
    try:
        return store.has_keys()
    except Exception:  # pragma: no cover - defensive
        return False


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer ") :].strip()
    return token or None


async def _require_api_key(request: Request) -> None:
    """Dependency: 校验 Bearer token（env 主密钥 或 注册表内的受管密钥）。

    Resolution order:

    1. ``MORE_API_KEY`` (legacy bootstrap key) — grants the wildcard scope and
       keeps every pre-existing deployment working unchanged.
    2. Registered keys from :mod:`more_core.security.api_key_store` — scoped,
       expiring and revocable.
    3. When *no* credential is configured at all the platform keeps its
       documented dev-mode contract and serves unauthenticated requests.
    """
    store = _key_store()
    expected = (os.getenv("MORE_API_KEY") or "").strip()
    registered = _has_registered_keys(store)

    if not expected and not registered:
        request.state.api_key_scopes = (WILDCARD_SCOPE,)
        request.state.principal = "dev-mode"
        set_principal("dev-mode")
        return

    token = _bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    if expected and hmac.compare_digest(token, expected):
        request.state.api_key_id = "env:MORE_API_KEY"
        request.state.api_key_scopes = (WILDCARD_SCOPE,)
        request.state.principal = principal_from_api_key_id("env:MORE_API_KEY")
        set_principal(request.state.principal)
        return

    record = store.verify(token) if store is not None else None
    if record is None:
        raise HTTPException(status_code=403, detail="Invalid API key")
    # 配额（每分钟调用上限）：超限 → 429，且只累加拒绝计数
    if record.quota_per_min:
        _client_ip = request.client.host if request.client else ""
        allowed, used, limit = store.quota_check(record.key_id)
        if not allowed:
            store.record_denied(record.key_id, ip=_client_ip)
            raise HTTPException(
                status_code=429,
                detail=(
                    f"API key quota exceeded: {used}/{limit} calls in the last minute "
                    f"(key={record.key_id})"
                ),
            )

    request.state.api_key_id = record.key_id
    request.state.api_key_scopes = record.scopes
    request.state.principal = principal_from_api_key_id(record.key_id)
    set_principal(request.state.principal)


def create_app(core: MoRECore | None = None) -> FastAPI:
    core = core or MoRECore.from_env()

    validate_api_key()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await core.start()
        try:
            yield
        finally:
            await core.stop()

    app = FastAPI(
        title="QNMing MoRE OS API",
        version=__version__,
        description="""QNMing MoRE OS — Neuro-Symbolic Metacognitive Self-Evolving Agent OS API (L0–L5).

## Features

- **Task Execution**: Execute tasks through the L0-L5 pipeline
- **LLM Management**: Manage LLM providers, state, and reasoning models
- **Hands**: Autonomous agent packages with lifecycle management
- **Skills**: Modular capabilities (web, code, config)
- **Workflows**: Multi-step orchestration with dependency resolution
- **Schedules**: Cron-based task scheduling
- **Channels**: Message platform adapters (Telegram, Discord, etc.)
- **Security**: RBAC, taint tracking, output filtering
- **Monitoring**: Real-time dashboard snapshots and health checks

## Authentication

Set `MORE_API_KEY` environment variable to enable API key authentication.
Include `Authorization: Bearer <key>` header for protected endpoints.
When the key is unset the API runs unauthenticated (dev mode) and logs a
warning. Set `MORE_REQUIRE_API_KEY=1` to refuse to start instead.
See docs/API_KEY.md for key format, rotation, and troubleshooting.

## Resources

- [GitHub Repository](https://github.com/QNMing/QNMing-MoRE-OS)
- [Architecture Documentation](https://github.com/QNMing/QNMing-MoRE-OS/blob/main/more_core/ARCHITECTURE.md)
""",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS — 默认放行本地开发端口（localhost 与 127.0.0.1 两种写法都要有）。
    # R-15：此前 `MORE_CORS_ORIGINS` 会**整体覆盖**默认值，而 .env 里只写了
    # localhost 变体；前端 dev server 绑 127.0.0.1 时 Origin 为
    # `http://127.0.0.1:3003`，不在白名单 → 响应缺少
    # `Access-Control-Allow-Origin` → 浏览器直接 "Failed to fetch"。
    # 现在改为"默认值 + 环境变量追加"，显式配置只能扩充、不会收窄开发来源。
    _default_cors_origins = [
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3002", "http://127.0.0.1:3002",
        "http://localhost:3003", "http://127.0.0.1:3003",
        "http://localhost:3004", "http://127.0.0.1:3004",
    ]
    _extra_origins = [
        o.strip() for o in os.getenv("MORE_CORS_ORIGINS", "").split(",") if o.strip()
    ]
    _allowed_origins = list(dict.fromkeys(_default_cors_origins + _extra_origins))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        allow_credentials=True,
    )

    # ── 用量采集中间件：为受管密钥记录每次调用的耗时/状态 ──────────
    @app.middleware("http")
    async def _api_key_usage_middleware(request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - started) * 1000.0
        key_id = getattr(request.state, "api_key_id", None)
        # env 主密钥不计配额；429 由 record_denied 计数，避免自锁
        if key_id and key_id != "env:MORE_API_KEY" and response.status_code != 429:
            try:
                _store = _key_store()
                if _store is not None:
                    _store.record_usage(
                        key_id,
                        endpoint=request.url.path,
                        status=response.status_code,
                        latency_ms=latency_ms,
                        ip=(request.client.host if request.client else ""),
                    )
            except Exception:  # pragma: no cover - 用量写入不得影响响应
                pass
        return response

    # Register modular routers
    app.include_router(create_health_router(core, _require_api_key))

    @app.get("/health", include_in_schema=False)
    async def _health_alias() -> Any:
        """R-16: 便捷别名 —— 浏览器习惯访问的 /health 之前是 404。"""
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/api/v1/health", status_code=307)
    app.include_router(create_tasks_router(core, _require_api_key))
    app.include_router(create_llm_router(core, _require_api_key))
    app.include_router(create_zen_router(core, _require_api_key))
    app.include_router(create_requirements_router(core, _require_api_key))
    app.include_router(create_hands_router(core, _require_api_key))
    app.include_router(create_channels_router(core, _require_api_key))
    app.include_router(create_cron_router(core, _require_api_key))
    app.include_router(create_skills_router(core, _require_api_key))
    app.include_router(create_commands_router(core, _require_api_key))
    app.include_router(create_security_router(core, _require_api_key))
    app.include_router(create_hotreload_router(core, _require_api_key))
    app.include_router(create_monitor_router(core, _require_api_key))
    app.include_router(create_delivery_router(core, _require_api_key))
    app.include_router(create_workflows_router(core, _require_api_key))
    app.include_router(create_deployments_router(core, _require_api_key))
    app.include_router(create_sessions_router(core, _require_api_key))
    app.include_router(create_outputs_router(core, _require_api_key))
    app.include_router(create_mcp_router(core, _require_api_key))
    app.include_router(create_a2a_router(core, _require_api_key))
    app.include_router(create_import_task_router(core, _require_api_key))
    app.include_router(create_deliberate_router(core, _require_api_key))
    app.include_router(create_admin_api_key_router(_require_api_key))

    return app
