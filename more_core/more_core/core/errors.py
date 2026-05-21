"""Typed exception hierarchy."""

from __future__ import annotations


class MoREError(Exception):
    """Base class for all MoRE Core errors."""


class PluginError(MoREError):
    """Plugin discovery / loading / activation / dependency errors."""


class LLMError(MoREError):
    """LLM provider connectivity, authentication, or generation errors."""


class SandboxError(MoREError):
    """Sandbox execution errors: timeout, resource limit, disallowed op."""


class GovernanceError(MoREError):
    """Ontology/policy violation or audit failure; stops task pipeline."""


class RoutingError(MoREError):
    """Layer router cannot resolve a target layer for the request."""
