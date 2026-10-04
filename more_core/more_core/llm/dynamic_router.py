"""Dynamic model router — env-driven, alias-aware, reasoning-integrated."""

from __future__ import annotations

import collections
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from ..core.types import TaskType
from .model_aliases import ModelAliasRegistry
from .provider import LLMRequest
from .reasoning import ReasoningRouter
from .task_router import (
    FALLBACK_CHAINS,
    MODEL_TIER_LADDER,
    PREV_MODEL_TIER_LADDER,
    PREV_TIER_PROVIDERS,
    T0_TASK_WHITELIST,
    TIER_0_DISABLED,
    TIER_MAX_TOKENS,
    TIER_PROVIDERS,
    TIER_SWITCH_COOLDOWN_S,
    TIER_THINKING,
    TaskModelRouter,
    tier_index_for_difficulty,
)
from .manager import ProviderModelPair as ModelBinding

if TYPE_CHECKING:
    from ..llm.manager import LLMManager

_log = logging.getLogger(__name__)

_ENV_PREFIX = "MORE_TASK_MODEL_"

# P1-4 G-3 覃朗：T0↔T1 翻转时间戳滚动窗口，用于 ?tier_transitions_rollup=1h/24h 运维面板聚合
_ROLLUP_WINDOWS: dict[str, int] = {"1h": 3600, "24h": 86400}


def _load_env_overrides() -> dict[TaskType, ModelBinding]:
    """Load task→model overrides from environment variables.

    Format: ``MORE_TASK_MODEL_<TASK_TYPE>=<provider>:<model>``
    Example: ``MORE_TASK_MODEL_CODE_GENERATION=ollama:qwen2.5:7b``
    """
    overrides: dict[TaskType, ModelBinding] = {}
    for key, val in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        task_name = key[len(_ENV_PREFIX) :].lower()
        try:
            task_type = TaskType(task_name)
        except ValueError:
            _log.warning("unknown task type in env: %s", key)
            continue
        parts = val.split(":", 1)
        if len(parts) != 2:
            _log.warning("invalid format for %s (expected provider:model)", key)
            continue
        overrides[task_type] = ModelBinding(provider=parts[0], model=parts[1])
        _log.info("env override: %s → %s/%s", task_type.value, parts[0], parts[1])
    return overrides


class DynamicModelRouter(TaskModelRouter):
    """Extends :class:`TaskModelRouter` with alias resolution, reasoning
    awareness, and runtime-configurable overrides via env vars or API calls.
    """

    def __init__(self, llm_manager: LLMManager) -> None:
        super().__init__(llm_manager)
        self._alias_registry = ModelAliasRegistry()
        self._reasoning_router = ReasoningRouter()
        self._custom_fallback_chains: dict[str, list[ModelBinding]] = {}
        # R1: tier switch hysteresis (覃朗专家 P0-4).  Cooldown state lives only
        # in memory — restarting the process zeroes it out (never persisted
        # to sqlite, see 运维与成本专家 §三 R1 约束).
        self._tier_last_effective_idx: dict[str, int] = {}
        self._tier_switch_cooldown_until: dict[str, float] = {}
        self._tier_cooldown_s: float = float(
            os.environ.get("MORE_TIER_SWITCH_COOLDOWN_S") or TIER_SWITCH_COOLDOWN_S
        )
        self._t0_whitelist: frozenset[TaskType] = T0_TASK_WHITELIST
        self._tier_status_last_log_ts: float = 0.0
        # Aggregate transition counters used by TierLadderStatus INFO log and
        # later by R3 `tier_transitions_per_hour`.
        self._tier_transition_count: dict[str, int] = {}
        # P1-4 G-3: 滚动窗口时间戳 (monotonic not wall-clock, 24h 上限避免内存无限增长)
        self._tier_transition_timestamps: collections.deque[float] = collections.deque(
            maxlen=100000
        )
        # P1-4 G-1/G-2: 保存当前梯子快照作为"last known current"以便 rollback 对比
        self._prev_ladder_models: tuple[str, ...] = PREV_MODEL_TIER_LADDER
        self._prev_ladder_providers: tuple[str, ...] = PREV_TIER_PROVIDERS
        self._cur_ladder_models: tuple[str, ...] = MODEL_TIER_LADDER
        self._cur_ladder_providers: tuple[str, ...] = TIER_PROVIDERS

        # Apply env overrides
        for tt, binding in _load_env_overrides().items():
            self._task_map[tt] = binding

    # -- R1: tier hysteresis + whitelist enforcement ------------------------

    @staticmethod
    def _cohort_key(task_type: TaskType | Any) -> str:
        """Stable grouping key for per-task-type cooldown.

        Falls back to ``"*"`` when ``task_type`` is not a real TaskType so the
        cooldown code path is still reachable even with bad upstream input
        (never-raises invariant).
        """
        if isinstance(task_type, TaskType):
            return str(task_type.value)
        try:
            s = str(task_type)
            return s or "*"
        except Exception:
            return "*"

    def _resolve_tier_with_hysteresis(
        self, task_type: TaskType | Any, theory_idx: int
    ) -> int:
        """Apply T0 whitelist cap then T0↔T1 cooldown.

        * Step 1 — whitelist cap: ``theory_idx == 0`` but task not on the
          reasoning-task whitelist → clamp to 1 (限流加固, 覃朗专家 R1-B) so
          random 10/10 difficulty classifications don't yank the 35B MoE
          thinking model for e.g. CODE_REVIEW.
        * Step 2 — hysteresis: if the cohort would *cross* T0↔T1 in the
          reverse direction of the last recorded effective tier AND the
          per-cohort cooldown hasn't elapsed, refuse to switch and return
          the previous tier.  T1↔T2 never gets cooldown (R1 原文：避免叠加反向伤害).
        """
        # 1. Whitelist cap for tier 0 access
        if theory_idx <= 0 and isinstance(task_type, TaskType):
            if task_type not in self._t0_whitelist:
                theory_idx = 1
        # Clamp to valid ladder range (defensive floor/ceiling)
        n = len(self._cur_ladder_models)
        theory_idx = max(0, min(n - 1, int(theory_idx)))
        cohort = self._cohort_key(task_type)
        last = self._tier_last_effective_idx.get(cohort, theory_idx)
        now = time.monotonic()

        # Determine if this is a "group 0 reverse direction" flip
        # (T0 -> T1 or T1 -> T0).  All other moves are allowed immediately.
        flipping_0_vs_1 = {theory_idx, last} == {0, 1}
        cd_until = self._tier_switch_cooldown_until.get(cohort, 0.0)
        if flipping_0_vs_1 and theory_idx != last and now < cd_until:
            # Refuse the switch — stay with the last effective tier.
            effective = last
        else:
            effective = theory_idx
            if flipping_0_vs_1 and theory_idx != last:
                # Real T0↔T1 transition just happened; record new cooldown
                # horizon and bump transition counters.
                self._tier_switch_cooldown_until[cohort] = now + max(0.0, self._tier_cooldown_s)
                self._tier_transition_count[cohort] = (
                    self._tier_transition_count.get(cohort, 0) + 1
                )
                # P1-4 G-3: 滚动窗口时间戳（使用 wall-clock time.time 方便真实时间窗口切片）
                try:
                    self._tier_transition_timestamps.append(time.time())
                except Exception:  # pragma: no cover - deque append OOM 极端情况忽略
                    pass
        self._tier_last_effective_idx[cohort] = effective
        self._maybe_emit_tier_status()
        return effective

    def _maybe_emit_tier_status(self) -> None:
        """Emit ``TierLadderStatus`` INFO row every 60s (R1-B observability).

        Format is intentionally compact so humans + log scrapers can both
        read it: one line with whitelist, cooldown, per-cohort counters.
        """
        now = time.monotonic()
        if now - self._tier_status_last_log_ts < 60.0:
            return
        self._tier_status_last_log_ts = now
        whitelist_csv = ",".join(sorted(tt.value for tt in self._t0_whitelist))
        total_transitions = sum(self._tier_transition_count.values())
        cd_cohorts = sum(
            1 for t in self._tier_switch_cooldown_until.values() if t > now
        )
        _log.info(
            "[tier-ladder-status] cooldown_s=%.1f t0_whitelist=[%s] "
            "cohorts_tracked=%d cohorts_in_cooldown=%d "
            "t0_t1_transitions_total=%d providers=%s",
            self._tier_cooldown_s,
            whitelist_csv,
            len(self._tier_last_effective_idx),
            cd_cohorts,
            total_transitions,
            ",".join(self._llm.list_providers()),
        )

    # -- properties ----------------------------------------------------------

    @property
    def alias_registry(self) -> ModelAliasRegistry:
        return self._alias_registry

    @property
    def reasoning_router(self) -> ReasoningRouter:
        return self._reasoning_router

    # -- alias-aware resolution ---------------------------------------------

    def resolve_alias(self, name: str) -> ModelBinding | None:
        """Resolve a model alias (e.g. ``free-coder``) to a binding.

        Returns ``None`` if the alias is unknown.
        """
        alias = self._alias_registry.resolve(name)
        if alias is None:
            return None
        return ModelBinding(provider=alias.provider, model=alias.model)

    def _tier_binding(
        self, difficulty: int | None, task_type: TaskType | Any = None
    ) -> ModelBinding:
        """Pick the model tier for a given difficulty (逐级降智), with R1
        whitelist + hysteresis when ``task_type`` is provided.
        """
        idx = tier_index_for_difficulty(difficulty)
        if task_type is not None:
            idx = self._resolve_tier_with_hysteresis(task_type, idx)
        return ModelBinding(
            provider=self._cur_ladder_providers[idx], model=self._cur_ladder_models[idx]
        )

    def tier_params(
        self, difficulty: int | None, task_type: TaskType | Any = None
    ) -> dict[str, Any]:
        """Generation params for a difficulty tier (性能平衡).

        - ``enable_thinking``: reasoning/main tiers think (True) so hard tasks
          get deep reasoning; light/fallback tiers skip thinking to avoid the
          30~150+ reasoning-token overhead measured on local MoE models.
        - ``max_tokens``: a floor that only raises the budget — never lowers it
          — so thinking models never run out of room mid-reasoning.
        """
        idx = tier_index_for_difficulty(difficulty)
        if task_type is not None:
            idx = self._resolve_tier_with_hysteresis(task_type, idx)
        return {
            "enable_thinking": TIER_THINKING[idx],
            "max_tokens": TIER_MAX_TOKENS[idx],
        }

    def apply_tier_params(
        self,
        request: LLMRequest,
        difficulty: int | None,
        task_type: TaskType | Any = None,
    ) -> LLMRequest:
        """Apply tier-balanced generation params onto an existing request.

        Mutates and returns the same request.  ``max_tokens`` is only raised
        (never lowered) so caller-set budgets are respected; ``enable_thinking``
        is only flipped on when the tier demands it.
        """
        if difficulty is None:
            return request
        params = self.tier_params(difficulty, task_type=task_type)
        if params["enable_thinking"]:
            request.enable_thinking = True
        if request.max_tokens is None or request.max_tokens < params["max_tokens"]:
            request.max_tokens = params["max_tokens"]
        return request

    def get_binding(
        self, task_type: TaskType, difficulty: int | None = None
    ) -> ModelBinding:
        binding = super().get_binding(task_type)
        # Difficulty-aware tier selection (逐级降智): easy tasks use the light
        # model, hard tasks use the strong model.
        if difficulty is not None:
            binding = self._tier_binding(difficulty, task_type=task_type)
        # Reasoning is opt-in: callers must pass actual difficulty/complexity.
        # Only apply the reasoning alias when its provider is actually
        # available (avoids routing local tasks to an unavailable cloud model);
        # otherwise fall back to the local T0 (strongest reasoning tier).
        if self._reasoning_router.should_use_reasoning(
            (difficulty or 0) / 10.0, 0
        ):
            alias = self._alias_registry.resolve("reasoning")
            if (
                alias is not None
                and alias.provider in self._llm.list_providers()
            ):
                return ModelBinding(provider=alias.provider, model=alias.model)
            # NOTE: difficulty=None → 5 (T1 主力) as safe floor; still >= T1,
            # not accidentally routed to T2 (difficulty=0 → light 9b).
            floor_diff = difficulty if difficulty is not None else 5
            # T0 reasoning-distilled is the fallback when alias provider
            # isn't available, so clamp to at least the T0 threshold (8+).
            t0_diff = max(floor_diff, 8)
            return self._tier_binding(t0_diff, task_type=task_type)
        return binding

    def get_fallback_chain(
        self, task_type: TaskType, difficulty: int | None = None
    ) -> list[ModelBinding]:
        if difficulty is not None:
            # 逐级降智: start from the tier matching this difficulty and
            # degrade to progressively weaker models on failure.  Consecutive
            # duplicate models are collapsed (e.g. T0 == T1 when both are 35b).
            start_raw = tier_index_for_difficulty(difficulty)
            start = self._resolve_tier_with_hysteresis(task_type, start_raw)
            chain: list[ModelBinding] = []
            for i in range(start, len(self._cur_ladder_models)):
                b = ModelBinding(
                    provider=self._cur_ladder_providers[i], model=self._cur_ladder_models[i]
                )
                if not chain or (chain[-1].provider, chain[-1].model) != (b.provider, b.model):
                    chain.append(b)
            return chain
        chain_key = self._determine_chain_key(task_type)
        if chain_key in self._custom_fallback_chains:
            return list(self._custom_fallback_chains[chain_key])
        return super().get_fallback_chain(task_type)

    # -- runtime configuration API ------------------------------------------

    def set_custom_fallback_chain(self, name: str, chain: list[ModelBinding]) -> None:
        """Register or update a named fallback chain."""
        self._custom_fallback_chains[name] = list(chain)
        _log.info("custom fallback chain '%s' set with %d pairs", name, len(chain))

    def remove_custom_fallback_chain(self, name: str) -> None:
        self._custom_fallback_chains.pop(name, None)

    # -- P1-4 G-2/G-3: prev ladder rollback + transition rollups ------------

    def get_rolling_transition_rollup(
        self, window_name: str | None = None
    ) -> dict[str, int]:
        """G-3 覃朗：返回 1h / 24h 滚动窗口的 T0↔T1 翻转计数。

        传入 window_name='1h' 或 '24h' 返回单值；否则返回所有已注册窗口的 dict。
        窗口裁剪在每次调用时完成，避免后台线程。
        """
        try:
            now = time.time()
            # 先裁剪 24h 之前的过期时间戳 (deque 迭代自左→右 = 旧→新)
            cutoff_24h = now - _ROLLUP_WINDOWS["24h"]
            while (
                self._tier_transition_timestamps
                and self._tier_transition_timestamps[0] < cutoff_24h
            ):
                self._tier_transition_timestamps.popleft()
            timestamps = list(self._tier_transition_timestamps)
            result: dict[str, int] = {}
            for name, window_s in _ROLLUP_WINDOWS.items():
                cutoff = now - window_s
                result[name] = sum(1 for t in timestamps if t >= cutoff)
            if window_name is None:
                return result
            return {window_name: result.get(window_name, 0)}
        except Exception:
            if window_name is None:
                return {n: 0 for n in _ROLLUP_WINDOWS}
            return {window_name: 0}

    def apply_previous_tier_ladder(self) -> dict[str, Any]:
        """G-2 覃朗：运行时把梯子从当前版切回 MORE_PREV_TIER_*_MODEL 定义的上一版。

        仅影响本 router 实例的后续路由决策（内存态，重启失效）。模块级全局
        ``MODEL_TIER_LADDER`` / ``TIER_PROVIDERS`` 不变，避免跨实例副作用。返回
        rollback 前后的四元组快照供审计与面板。
        """
        before = {
            "models": list(self._cur_ladder_models),
            "providers": list(self._cur_ladder_providers),
        }
        new_models = self._prev_ladder_models
        new_providers = self._prev_ladder_providers
        # 安全护栏：prev 梯子长度必须与当前梯子一致 (4 tiers)，否则拒绝回滚
        if len(new_models) != len(self._cur_ladder_models) or len(new_providers) != len(
            self._cur_ladder_providers
        ):
            return {
                "rolled_back": False,
                "reason": "prev ladder length mismatch (expected 4 tiers)",
                "before": before,
                "after": before,
            }
        swapped_models = tuple(self._cur_ladder_models)
        swapped_providers = tuple(self._cur_ladder_providers)
        self._cur_ladder_models = tuple(new_models)
        self._cur_ladder_providers = tuple(new_providers)
        # next: swap prev = old current, so repeated rollbacks act as "toggle"
        self._prev_ladder_models = swapped_models
        self._prev_ladder_providers = swapped_providers
        after = {
            "models": list(self._cur_ladder_models),
            "providers": list(self._cur_ladder_providers),
        }
        _log.warning(
            "tier ladder rolled back via ops API: before=%s after=%s", before, after
        )
        return {"rolled_back": True, "before": before, "after": after}

    def get_routing_config(self) -> dict[str, Any]:
        """Full routing configuration, suitable for API serialization."""
        # G-3: default 1h/24h rollup counts for the 运维面板
        rollups = self.get_rolling_transition_rollup()
        cur_ladder = [
            {"provider": p, "model": m}
            for p, m in zip(self._cur_ladder_providers, self._cur_ladder_models)
        ]
        prev_ladder = [
            {"provider": p, "model": m}
            for p, m in zip(self._prev_ladder_providers, self._prev_ladder_models)
        ]
        return {
            "tier_0_disabled": bool(TIER_0_DISABLED),
            "tier_cooldown_s": self._tier_cooldown_s,
            "t0_whitelist": sorted(tt.value for tt in self._t0_whitelist),
            "bindings": self.list_bindings(),
            "fallback_chains": {
                k: [{"provider": p, "model": p.model} for p in v if hasattr(p, "provider")]
                for k, v in {**FALLBACK_CHAINS, **self._custom_fallback_chains}.items()
            },
            "aliases": self._alias_registry.to_api_dict(),
            "reasoning": self._reasoning_router.stats(),
            "tiers": {
                "disabled_tier_0": bool(TIER_0_DISABLED),
                "ladder": cur_ladder,
                "prev_ladder": prev_ladder,  # G-1 上一版梯子
                "thinking": list(TIER_THINKING),
                "max_tokens": list(TIER_MAX_TOKENS),
            },
            "failure_counts": dict(self._failure_count),
            "providers": self._llm.list_providers(),
            "transitions_t0_t1_total": sum(self._tier_transition_count.values()),
            "tier_transitions_rollup": rollups,  # G-3: {"1h": N, "24h": N}
        }

    def update_task_binding(self, task_type: TaskType, provider: str, model: str) -> None:
        """Set a custom binding for a task type.  Accepts alias in *model*."""
        resolved = self.resolve_alias(model) or ModelBinding(provider=provider, model=model)
        self.set_binding(task_type, resolved)

    def update_fallback_chain(self, name: str, chain: list[dict[str, str]]) -> None:
        """Set a fallback chain from API-friendly dict list."""
        pairs = [ModelBinding(provider=p["provider"], model=p["model"]) for p in chain]
        self.set_custom_fallback_chain(name, pairs)

    def get_llm_kwargs(self, task_type: TaskType) -> dict[str, Any]:
        """Build extra kwargs for :meth:`LLMManager.generate`."""
        return self.get_llm_kwargs_with_difficulty(task_type, 0)

    def get_llm_kwargs_with_difficulty(
        self, task_type: TaskType, difficulty: int
    ) -> dict[str, Any]:
        """Build extra kwargs with actual difficulty for reasoning routing."""
        binding = self.get_binding(task_type, difficulty=difficulty)
        extra: dict[str, Any] = {
            "provider": binding.provider,
            "model_override": binding.model,
        }
        if self._reasoning_router.should_use_reasoning(difficulty / 10.0, 0):
            extra["extra_params"] = self._reasoning_router.get_params_for_model(binding.model)
        return extra

    def select_provider(self, task_type: TaskType, difficulty: int | None = None) -> str | None:
        """Select best provider, optionally considering task difficulty."""
        binding = self.get_binding(task_type, difficulty=difficulty)
        if binding.provider in self._llm.list_providers():
            return binding.provider
        return None

    def select_model(self, task_type: TaskType, difficulty: int | None = None) -> str:
        """Select best model, optionally considering task difficulty."""
        return self.get_binding(task_type, difficulty=difficulty).model
