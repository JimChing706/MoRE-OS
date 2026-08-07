"""Code generation support — repo-aware context injection + multi-agent review.

Provides :func:`build_repo_context`, which scans a project root and produces
a compact map of module paths, top-level symbols, and HTTP routes so the
L0 generator can reference existing code (repo-aware generation, BPR B), and
:func:`run_code_review`, a parallel reviewer panel over generated code
(multi-agent review / Self-Audit, BPR C).
"""

from .context import build_repo_context
from .review import CodeReviewResult, ReviewerFinding, run_code_review

__all__ = ["build_repo_context", "CodeReviewResult", "ReviewerFinding", "run_code_review"]
