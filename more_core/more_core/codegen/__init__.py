"""Code generation support — repo-aware context injection for L0 prompts.

Provides :func:`build_repo_context`, which scans a project root and produces
a compact map of module paths, top-level symbols, and HTTP routes so the
L0 generator can reference existing code (repo-aware generation, BPR B).
"""

from .context import build_repo_context

__all__ = ["build_repo_context"]
