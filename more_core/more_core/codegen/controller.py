"""Codegen loop Controller — success-criteria aggregation + exit adjudication.

The Controller is the lightweight metacognition role of the codegen Agentic
Loop (CODEGEN_LOOP_SPEC §3/§4): it aggregates the pipeline's gate signals
(sandbox / acceptance assertions / review panel / differential / stagnation /
safety block) into a structured exit verdict and, when the loop exhausts its
rounds without meeting the success criteria, escalates to P0 manual takeover
while preserving all intermediate artifacts for the human.

Adjudication is fully deterministic (no LLM): "code can answer it" per the
MoRE rules — only judgement-class tasks go to a model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .evolution_signal import CodegenRunContext, export_codegen_evolution_signal

_log = logging.getLogger(__name__)

DECISION_PASS = "pass"
DECISION_PARTIAL = "partial"
DECISION_ESCALATED = "escalated"


@dataclass
class CodegenVerdict:
    """Controller exit verdict for one codegen fix-loop run."""

    decision: str  # pass | partial | escalated
    checks: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.decision == DECISION_PASS

    @property
    def summary(self) -> str:
        if self.decision == DECISION_PASS:
            return "codegen loop passed all success criteria"
        head = (
            "codegen loop partial"
            if self.decision == DECISION_PARTIAL
            else "codegen loop escalated to P0"
        )
        return f"{head}: " + "; ".join(self.reasons) if self.reasons else head

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "checks": self.checks,
            "reasons": self.reasons,
            "artifacts": self.artifacts,
        }


def _review_state(scratch: dict[str, Any], scope: str) -> str | None:
    if scratch.get(f"{scope}_review_rejected"):
        return "rejected"
    if scratch.get(f"{scope}_review_approved"):
        return "approved"
    return None


def _last_sandbox_result(scratch: dict[str, Any], scope: str) -> Any:
    """取出该 scope 最近一次沙箱结果（兼容 code/test 与历史键名）。"""
    for key in (
        f"{scope}_result",
        "sandbox_result" if scope == "code" else f"{scope}_sandbox_result",
    ):
        value = scratch.get(key)
        if value is not None:
            return value
    return None


def _last_sandbox_error(scratch: dict[str, Any], scope: str) -> str:
    """沙箱失败原因（截断），用于让升级结论可诊断。"""
    result = _last_sandbox_result(scratch, scope)
    if result is None:
        return ""
    err = getattr(result, "error", "") or ""
    if not err:
        err = str(getattr(result, "output", "") or "")
    return str(err)[:600]


def _last_sandbox_output(scratch: dict[str, Any], scope: str) -> str:
    result = _last_sandbox_result(scratch, scope)
    if result is None:
        return ""
    return str(getattr(result, "output", "") or "")[-300:]


def adjudicate_codegen(
    scratch: dict[str, Any],
    *,
    scope: str,
    sbx_success: bool,
    max_rounds: int = 3,
    assertions_required: bool = False,
    run_ctx: CodegenRunContext | None = None,
) -> CodegenVerdict:
    """Adjudicate a finished L0 fix loop against the BPR success criteria.

    Decision matrix (worst-wins, first match):
      1. safety block                → **escalated** (never deliver dangerous code)
      2. sandbox failed              → **escalated** (rounds exhausted, still failing)
      3. assertions required, not verified → **escalated**
      4. review panel rejected       → **escalated** (P1/P2 unfixed → P0 takeover)
      5. review approved w/ P3 only  → **partial**   (P3 allowed with explanation)
      6. otherwise                   → **pass**

    Intermediate artifacts (iterations, review summary, differential/stagnation
    flags) are preserved on the verdict so an escalation keeps everything a
    human needs for P0 takeover.

    When *run_ctx* is provided the verdict is persisted via
    :func:`export_codegen_evolution_signal` so L2 can aggregate "which fixes
    actually worked" across restarts — closes the Step-2 evolution feedback
    gap.  Export is best-effort; the verdict is always returned regardless.
    """
    blocked = bool(scratch.get(f"{scope}_fix_blocked") or scratch.get(f"{scope}_blocked"))
    review = _review_state(scratch, scope)
    review_p3 = bool(scratch.get(f"{scope}_review_p3"))
    checks: dict[str, Any] = {
        "sandbox": bool(sbx_success),
        "assertions": bool(scratch.get(f"{scope}_verified")),
        "review": review,
        "review_p3": review_p3,
        "differential": bool(scratch.get(f"{scope}_differential")),
        "stagnant": bool(scratch.get(f"{scope}_fix_stagnant")),
        "blocked": blocked,
    }

    reasons: list[str] = []
    if blocked:
        decision = DECISION_ESCALATED
        reasons.append(f"safety check blocked ({scope})")
    elif not sbx_success:
        rounds = scratch.get(f"{scope}_fix_iterations", 0)
        decision = DECISION_ESCALATED
        reasons.append(f"sandbox failed after {rounds}/{max_rounds} fix rounds ({scope})")
    elif assertions_required and not checks["assertions"]:
        decision = DECISION_ESCALATED
        reasons.append(f"acceptance assertions not verified ({scope})")
    elif review == "rejected":
        decision = DECISION_ESCALATED
        reasons.append(f"code review rejected with P1/P2 findings ({scope})")
    elif review == "approved" and review_p3:
        decision = DECISION_PARTIAL
        reasons.append(f"code review approved with P3 findings only ({scope})")
    else:
        decision = DECISION_PASS

    if checks["differential"] and decision != DECISION_PASS:
        reasons.append("differential outputs disagreed (no trusted clean candidate)")
    if checks["stagnant"] and decision != DECISION_PASS:
        reasons.append("fix loop converged with no progress (stagnation guard)")

    # ── Step-4 fusion: pick up delegation markers from scratch ──────
    delegated_flag = bool(scratch.get("_chassis_delegated") or scratch.get(f"{scope}_delegated"))
    delegation_trigger = str(
        scratch.get("_chassis_delegation_trigger")
        or scratch.get(f"{scope}_delegation_trigger")
        or ""
    )
    delegation_state = str(
        scratch.get("_chassis_delegation_state") or scratch.get(f"{scope}_delegation_state") or ""
    )

    artifacts: dict[str, Any] = {
        "scope": scope,
        "fix_iterations": scratch.get(f"{scope}_fix_iterations", 0),
        "max_rounds": max_rounds,
        "best_of_k": bool(scratch.get(f"{scope}_best_of_k")),
        "review_summary": scratch.get(f"{scope}_review_summary"),
        "differential": checks["differential"],
        "stagnant": checks["stagnant"],
        "violations": scratch.get(f"{scope}_fix_blocked") or scratch.get(f"{scope}_blocked"),
        "delegated": delegated_flag,
        "delegation_trigger": delegation_trigger,
        "delegation_state": delegation_state,
        # R-20：保留**最后一次沙箱失败的真实原因**。此前 escalated 只记录
        # "sandbox failed after N rounds"，无法区分"代码真错"与"沙箱超时/工具缺失"，
        # 使升级结论不可诊断。
        "last_error": _last_sandbox_error(scratch, scope),
        "last_output_tail": _last_sandbox_output(scratch, scope),
        "timed_out": bool(getattr(_last_sandbox_result(scratch, scope), "timed_out", False)),
    }

    # D-1：统一判据语义 —— 给 escalated 打上可诊断的原因分类
    from .escalation import classify_escalation

    info = classify_escalation(decision=decision, checks=checks, artifacts=artifacts)
    artifacts["cause"] = info.cause.value
    artifacts["cause_detail"] = info.detail
    artifacts["is_infra"] = info.is_infra
    if decision != DECISION_PASS:
        reasons.append(f"cause={info.cause.value}")

    verdict = CodegenVerdict(
        decision=decision,
        checks=checks,
        reasons=reasons,
        artifacts=artifacts,
    )

    if run_ctx is not None:
        try:
            if not run_ctx.scope:
                run_ctx.scope = scope
            run_id = export_codegen_evolution_signal(
                verdict,
                scratch,
                run_ctx=run_ctx,
            )
            if run_id:
                artifacts["evolution_run_id"] = run_id
                verdict.artifacts["evolution_run_id"] = run_id
        except Exception as exc:  # pragma: no cover - never break the verdict path  # noqa: BLE001
            _log.debug("adjudicate_codegen: evolution signal export skipped: %s", exc)

    return verdict
