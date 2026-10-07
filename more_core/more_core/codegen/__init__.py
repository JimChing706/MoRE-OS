"""Code generation support — repo-aware context injection + multi-agent review.

Provides :func:`build_repo_context`, which scans a project root and produces
a compact map of module paths, top-level symbols, and HTTP routes so the
L0 generator can reference existing code (repo-aware generation, BPR B),
:func:`run_code_review`, a parallel reviewer panel over generated code
(multi-agent review / Self-Audit, BPR C), and :func:`adjudicate_codegen`, the
deterministic Controller that aggregates the loop's gate signals into an exit
verdict and escalates to P0 manual takeover when rounds are exhausted (BPR D).
"""

from .context import build_repo_context
from .controller import (
    DECISION_ESCALATED,
    DECISION_PARTIAL,
    DECISION_PASS,
    CodegenVerdict,
    adjudicate_codegen,
)
from .review import CodeReviewResult, ReviewerFinding, run_code_review

__all__ = [
    "DECISION_ESCALATED",
    "DECISION_PARTIAL",
    "DECISION_PASS",
    "CodeReviewResult",
    "CodegenVerdict",
    "ReviewerFinding",
    "adjudicate_codegen",
    "build_repo_context",
    "run_code_review",
]
