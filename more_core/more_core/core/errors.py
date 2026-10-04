"""Typed exception hierarchy."""

from __future__ import annotations


class MoREError(Exception):
    """Base class for all MoRE Core errors."""


class PluginError(MoREError):
    """Plugin discovery / loading / activation / dependency errors."""


class LLMError(MoREError):
    """LLM provider connectivity, authentication, or generation errors."""


class ThinkingBudgetExhaustedError(LLMError):
    """Reasoning model produced too little real answer vs thinking tokens.

    Triggered when either:
      * ``(completion_tokens or answer_len) / max_tokens < 0.2`` — the requested
        output budget was mostly eaten by thinking tokens, leaving no usable
        answer for downstream L0 / sandbox.
      * ``completion_tokens > 0 but output text.strip() == ""`` — state looks
        COMPLETED but the answer payload is empty.
      * ``answer_tokens / (thinking_tokens + 1) < 0.2`` with sufficient thinking
        volume (``thinking_tokens >= 50``) — chain-of-thought dominated.

    **Safety invariant**: the error message never embeds the model's raw
    completion or thinking payload.  Only token counts and numeric ratios are
    included so tracebacks are safe to log / return.
    """


class SandboxError(MoREError):
    """Sandbox execution errors: timeout, resource limit, disallowed op."""


class GovernanceError(MoREError):
    """Ontology/policy violation or audit failure; stops task pipeline."""


class RoutingError(MoREError):
    """Layer router cannot resolve a target layer for the request."""


class CouncilError(MoREError):
    """Multi-role cognitive council errors."""


class MCPError(MoREError):
    """MCP protocol client/server errors."""


class WorkflowError(MoREError):
    """Workflow engine errors."""
