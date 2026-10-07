"""Hands module — Autonomous Agent Packages for QNMing MoRE OS.

Inspired by OpenFang Hands: pre-built autonomous capability packages
that run independently, on schedules, without user prompting.

Each Hand bundles:
- Manifest (HandManifest): metadata, tools, settings, schedule
- System prompt: multi-phase operational playbook
- Skill references: domain expertise injected at runtime
- Guardrails: approval gates for sensitive actions
"""

from .base import Hand, HandManifest, HandResult, HandStatus
from .manager import HandManager
from .registry import HandRegistry

__all__ = [
    "Hand",
    "HandManager",
    "HandManifest",
    "HandRegistry",
    "HandResult",
    "HandStatus",
]
