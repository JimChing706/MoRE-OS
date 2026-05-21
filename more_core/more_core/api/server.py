"""QNMing MoRE OS — FastAPI platform API.

Keeps the surface minimal and *domain-neutral*: any industry verb goes
through plugins, never through hard-coded endpoints.

Endpoints are organised into modular routers under ``api/routers/``.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

try:
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "QNMing MoRE OS API requires the 'api' extra: pip install 'qnming-more-os[api]'"
    ) from exc

from ..runtime.orchestrator import MoRECore
from ..version import __version__
from .routers import (
    create_health_router,
    create_tasks_router,
    create_llm_router,
    create_zen_router,
    create_requirements_router,
    create_hands_router,
    create_channels_router,
    create_cron_router,
    create_skills_router,
    create_commands_router,
    create_security_router,
    create_hotreload_router,
    create_monitor_router,
    create_workflows_router,
    create_deployments_router,
    create_sessions_router,
)

_log = logging.getLogger(__name__)


async def _require_api_key(
    authorization: str | None = Header(None, alias="Authorization"),
) -> None:
    """Dependency: reject requests when MORE_API_KEY is set and token is wrong."""
    expected = os.getenv("MORE_API_KEY", "")
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if authorization[7:] != expected:
        raise HTTPException(status_code=403, detail="Invalid API key")


def create_app(core: MoRECore | None = None) -> FastAPI:
    core = core or MoRECore.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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

## Resources

- [GitHub Repository](https://github.com/QNMing/QNMing-MoRE-OS)
- [Architecture Documentation](https://github.com/QNMing/QNMing-MoRE-OS/blob/main/more_core/ARCHITECTURE.md)
""",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS — restricted to configured origins
    _raw_origins = os.getenv(
        "MORE_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3002,http://127.0.0.1:3002,http://localhost:3003,http://127.0.0.1:3003"
    )
    _allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins or ["http://localhost:3000"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        allow_credentials=True,
    )

    # Register modular routers
    app.include_router(create_health_router(core))
    app.include_router(create_tasks_router(core, _require_api_key))
    app.include_router(create_llm_router(core, _require_api_key))
    app.include_router(create_zen_router(core, _require_api_key))
    app.include_router(create_requirements_router(core, _require_api_key))
    app.include_router(create_hands_router(core, _require_api_key))
    app.include_router(create_channels_router(core))
    app.include_router(create_cron_router(core, _require_api_key))
    app.include_router(create_skills_router(core, _require_api_key))
    app.include_router(create_commands_router(core))
    app.include_router(create_security_router(core, _require_api_key))
    app.include_router(create_hotreload_router(core, _require_api_key))
    app.include_router(create_monitor_router(core))
    app.include_router(create_workflows_router(core, _require_api_key))
    app.include_router(create_deployments_router(core, _require_api_key))
    app.include_router(create_sessions_router(core))

    return app
