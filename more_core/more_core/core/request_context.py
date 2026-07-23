"""Request context for correlation ID tracking and structured logging.

Provides a lightweight async-safe context variable that carries a correlation
ID through the entire request lifecycle, making distributed tracing trivial.
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any


# Async-safe context variable for request correlation
_request_ctx: contextvars.ContextVar["RequestContext | None"] = contextvars.ContextVar(
    "more_request_ctx", default=None
)


@dataclass(slots=True)
class RequestContext:
    """Carries correlation metadata through an async request lifecycle."""

    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    task_id: str = ""
    actor: str = "anonymous"
    extra: dict[str, Any] = field(default_factory=dict)


def get_context() -> RequestContext | None:
    """Get the current request context (None outside a request)."""
    return _request_ctx.get()


def set_context(ctx: RequestContext) -> contextvars.Token[RequestContext | None]:
    """Set the request context for the current async task."""
    return _request_ctx.set(ctx)


def clear_context(token: contextvars.Token[RequestContext | None]) -> None:
    """Reset context after request completes."""
    _request_ctx.reset(token)


class CorrelationFilter(logging.Filter):
    """Inject correlation_id into all log records automatically."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _request_ctx.get()
        record.correlation_id = ctx.correlation_id if ctx else "-"
        record.task_id = ctx.task_id if ctx else "-"
        return True


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Configure root logger with correlation-aware structured format."""
    fmt = "[%(asctime)s] %(levelname)s [%(correlation_id)s] %(name)s: %(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    handler.addFilter(CorrelationFilter())

    root = logging.getLogger("more_core")
    root.setLevel(level)
    # Avoid duplicate handlers on repeated calls
    if not any(
        isinstance(h, logging.StreamHandler) and hasattr(h, "_more_configured")
        for h in root.handlers
    ):
        handler._more_configured = True  # type: ignore[attr-defined]
        root.addHandler(handler)
