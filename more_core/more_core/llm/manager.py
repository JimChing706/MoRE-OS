"""LLM Manager: multi-provider routing with intelligent fallback chains."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, AsyncIterator, cast

from ..core.config import LLMProviderConfig
from ..core.errors import LLMError, ThinkingBudgetExhaustedError
from .provider import LLMProvider, LLMRequest, LLMResponse
from .providers.ollama import OllamaProvider
from .providers.lmstudio import LMStudioProvider
from .providers.openai_compat import OpenAICompatProvider
from .providers.deepseek import DeepSeekProvider
from .providers.mock import MockProvider


_CACHE_MAX = 256
# Wall-clock budget for the whole serial fallback chain (all providers tried).
# Guards against the pathological case: N providers × 5 retries × 120s timeout
# with no total bound, which previously could stall a task for ~750s+.
# 可用 MORE_LLM_FALLBACK_DEADLINE_S 覆盖：本地 35B 推理模型较慢时需放宽，
# 否则每次调用都会在链级预算耗尽 → TimeoutError（历史"成功率 0%"事故）。
_FALLBACK_DEADLINE_S = float(os.getenv("MORE_LLM_FALLBACK_DEADLINE_S", "90") or 90)
# CLOSEDSPEC P1-3 R4-B 覃朗：把 DeliverableContract.timeout_s 和 LLM fallback deadline 联动绑定。
# 预留 5s 给上层合约 kill switch 做清理；若 contract 超时极短则兜底 1s 地板。
_FALLBACK_CONTRACT_HEADROOM_S = 5.0
_FALLBACK_MIN_EFFECTIVE_S = 1.0


def _exc_summary(exc: BaseException, elapsed_ms: float) -> str:
    """人类可读的失败原因。

    ``asyncio.TimeoutError``/``TimeoutError`` 的 ``str()`` 是空串，直接记录会让
    遥测里出现 ``error=''``，无法区分"超时"与"其他失败"。这里显式命名超时，
    并在其他异常消息为空时回退到异常类型名。
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return f"provider timeout after {elapsed_ms:.0f}ms"
    text = str(exc).strip()
    return text or type(exc).__name__


def _effective_fallback_deadline(contract_timeout_s: float | None) -> float:
    """R4-B: 计算 effective fallback deadline。

    ``effective = min(contract_timeout_s - 5s headroom, 90s cap)``
    若未传 contract 超时则返回默认 90s。结果地板值 = 1s（避免 0 / 负窗口）。
    """
    if contract_timeout_s is None or contract_timeout_s <= 0:
        return _FALLBACK_DEADLINE_S
    bounded = contract_timeout_s - _FALLBACK_CONTRACT_HEADROOM_S
    return max(_FALLBACK_MIN_EFFECTIVE_S, min(bounded, _FALLBACK_DEADLINE_S))


# LLM response cache TTL: stale responses must not be reused indefinitely.
_CACHE_TTL_S = 300.0
# Per-provider health-check wall-clock bound.  A hanging endpoint must not
# consume the whole fallback deadline (or the provider timeout of 120s)
# — the fallback total deadline only starts ticking afterwards.
_HEALTH_CHECK_TIMEOUT_S = 5.0
# Failure-count TTL: repeated transient failures must not disable a provider
# forever.  After this window without a new failure the count is forgotten.
_FAILURE_TTL_S = 60.0

_logger = logging.getLogger(__name__)

#: 判定"确定性模型故障"的关键字（加载失败 / 模型不存在 / 路由不存在）
_HARD_MODEL_FAILURE_HINTS = (
    "failed to load model",
    "model not found",
    "no such model",
    "unknown model",
    "does not exist",
    "failed to load",
)
_HARD_FAILURE_THRESHOLD = 3


def _is_hard_model_failure(error: str) -> bool:
    lowered = (error or "").lower()
    return any(h in lowered for h in _HARD_MODEL_FAILURE_HINTS)


# ── Thinking-tag stripping (R2-B) ─────────────────────────────────────────
# Matches common CoT thinking wrappers.  Case-insensitive and tolerant of
# whitespace / attributes.  A missing closing tag is treated as "strip
# everything from opening tag to end of string" so partial thinking payloads
# never leak (S-3 invariant).
_STRIP_PATTERNS: list[tuple[re.Pattern[str], re.Pattern[str]]] = [
    (re.compile(r"<\s*think[^>]*\s*>", re.I | re.S), re.compile(r"<\s*/\s*think\s*>", re.I | re.S)),
    (
        re.compile(r"<\s*reasoning[^>]*\s*>", re.I | re.S),
        re.compile(r"<\s*/\s*reasoning\s*>", re.I | re.S),
    ),
    (
        re.compile(r"<\s*chain[_-]?of[_-]?thought[^>]*\s*>", re.I | re.S),
        re.compile(r"<\s*/\s*chain[_-]?of[_-]?thought\s*>", re.I | re.S),
    ),
    (
        re.compile(r"<\s*thought[^>]*\s*>", re.I | re.S),
        re.compile(r"<\s*/\s*thought\s*>", re.I | re.S),
    ),
    (
        re.compile(r"<\|\s*Begin\s+of\s+Thought\s*\|>", re.I | re.S),
        re.compile(r"<\|\s*End\s+of\s+Thought\s*\|>", re.I | re.S),
    ),
    (re.compile(r"<\|\s*BOT\s*\|>", re.I | re.S), re.compile(r"<\|\s*EOT\s*\|>", re.I | re.S)),
    (
        re.compile(r"<\|\s*thinking_begin\s*\|>", re.I | re.S),
        re.compile(r"<\|\s*thinking_end\s*\|>", re.I | re.S),
    ),
]

# Global metrics counters (lightweight; no lock needed for Python int += 1).
_THINKING_STRIPPED_TOTAL = 0
_THINKING_STRIPPED_WINDOW = 0
_THINKING_STRIPPED_WINDOW_START = 0.0
_THINKING_STRIPPED_ALERT_THRESHOLD = 100  # per-hour WARN threshold (R2-B SRE)


def _strip_thinking_tags(content: str) -> tuple[str, int, str]:
    """Strip known chain-of-thought wrappers from ``content``.

    Returns ``(clean_content, n_tags_stripped, stripped_reasoning_text)``.
    ``stripped_reasoning_text`` is the concatenation of everything we removed
    so it can be stowed in ``LLMResponse.reasoning_content`` for token
    ratio accounting later.  Nothing ever embeds this in an error message.
    """
    if not content:
        return content or "", 0, ""
    stripped: list[str] = []
    n = 0
    result = content
    for open_re, close_re in _STRIP_PATTERNS:
        while True:
            m = open_re.search(result)
            if not m:
                break
            start = m.start()
            open_end = m.end()
            mc = close_re.search(result, open_end)
            if mc:
                end = mc.end()
                chunk = result[open_end : mc.start()]
            else:
                # Unclosed tag — drop everything from open tag to EOS
                end = len(result)
                chunk = result[open_end:]
            stripped.append(chunk)
            n += 1
            result = result[:start] + result[end:]
    return result, n, "\n".join(stripped)


def _bump_stripped_metrics(n_stripped: int) -> None:
    """Increment counters; emit a WARN log if hourly threshold is breached."""
    global _THINKING_STRIPPED_TOTAL, _THINKING_STRIPPED_WINDOW, _THINKING_STRIPPED_WINDOW_START
    if n_stripped <= 0:
        return
    now = time.monotonic()
    if _THINKING_STRIPPED_WINDOW_START == 0.0:
        _THINKING_STRIPPED_WINDOW_START = now
    elapsed = now - _THINKING_STRIPPED_WINDOW_START
    if elapsed >= 3600.0:
        _THINKING_STRIPPED_WINDOW = 0
        _THINKING_STRIPPED_WINDOW_START = now
    _THINKING_STRIPPED_TOTAL += n_stripped
    _THINKING_STRIPPED_WINDOW += n_stripped
    if elapsed < 3600.0 and _THINKING_STRIPPED_WINDOW >= _THINKING_STRIPPED_ALERT_THRESHOLD:
        _logger.warning(
            "Thinking tags stripped %d times in %.0fs (>=%d/h threshold). "
            "Provider may be leaking chain-of-thought via content field.",
            _THINKING_STRIPPED_WINDOW,
            elapsed,
            _THINKING_STRIPPED_ALERT_THRESHOLD,
        )


# Approximate token counters used when provider omits explicit prompt /
# completion / reasoning token counts.  1 token ≈ 4 chars is a conservative
# English-agnostic heuristic; Chinese text tends toward ~1.8 chars / token so
# 4 is intentionally safe (over-estimates, meaning R2 fires LESS often).
_CHARS_PER_TOKEN = 4


def _approx_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


class _LRU:
    """True LRU with TTL.  Reads refresh recency; expired entries are purged."""

    def __init__(self) -> None:
        self._data: OrderedDict[str, tuple[float, LLMResponse]] = OrderedDict()

    def put(self, key: str, value: LLMResponse) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (time.monotonic(), value)
        if len(self._data) > _CACHE_MAX:
            self._data.popitem(last=False)

    def get(self, key: str, default: LLMResponse | None = None) -> LLMResponse | None:
        item = self._data.get(key)
        if item is None:
            return default
        ts, value = item
        if time.monotonic() - ts > _CACHE_TTL_S:
            del self._data[key]
            return default
        self._data.move_to_end(key)
        return value

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data


def _build_provider(cfg: LLMProviderConfig) -> LLMProvider:
    if cfg.provider == "ollama":
        return cast(
            "LLMProvider",
            OllamaProvider(
                name=cfg.name, endpoint=cfg.endpoint, model=cfg.model, timeout=cfg.timeout_s
            ),
        )
    if cfg.provider == "lmstudio":
        return cast(
            "LLMProvider",
            LMStudioProvider(
                name=cfg.name,
                endpoint=cfg.endpoint,
                model=cfg.model,
                api_key=cfg.api_key,
                timeout=cfg.timeout_s,
            ),
        )
    if cfg.provider == "deepseek":
        return cast(
            "LLMProvider",
            DeepSeekProvider(
                name=cfg.name,
                endpoint=cfg.endpoint or "https://api.deepseek.com",
                model=cfg.model or "deepseek-chat",
                api_key=cfg.api_key or "",
                timeout=cfg.timeout_s,
            ),
        )
    if cfg.provider == "llamacpp":
        return cast(
            "LLMProvider",
            OpenAICompatProvider(
                name=cfg.name,
                endpoint=cfg.endpoint,
                model=cfg.model,
                api_key=cfg.api_key or "EMPTY",
                timeout=cfg.timeout_s,
            ),
        )
    if cfg.provider == "mock":
        return cast("LLMProvider", MockProvider())
    # All other providers use the OpenAI-compatible chat/completions API
    _OPENAI_COMPAT = {
        "openai",
        "anthropic",
        "custom",
        "azure",
        "google",
        "groq",
        "mistral",
        "cohere",
        "openrouter",
        "together",
        "xai",
        "sambanova",
        "fireworks",
        "perplexity",
        "cerebras",
        "huggingface",
        "replicate",
        "vllm",
    }
    if cfg.provider in _OPENAI_COMPAT:
        return cast(
            "LLMProvider",
            OpenAICompatProvider(
                name=cfg.name,
                endpoint=cfg.endpoint,
                model=cfg.model,
                api_key=cfg.api_key or "",
                timeout=cfg.timeout_s,
            ),
        )
    raise LLMError(f"unsupported provider: {cfg.provider}")


@dataclass
class ProviderModelPair:
    """A provider and model pair for fallback chains."""

    provider: str
    model: str


@dataclass
class FallbackChain:
    """A complete fallback chain with multiple provider-model pairs."""

    pairs: list[ProviderModelPair]


class LLMManager:
    """Routes an :class:`LLMRequest` through configured fallback chains.

    Reads :class:`LLMStateManager` at generate-time to apply runtime
    overrides (provider / model / temperature / max_tokens) set by the
    frontend or API — see :meth:`generate`.
    """

    def __init__(
        self,
        providers: list[LLMProviderConfig],
        fallback_chain: list[str] | None = None,
        state_manager: Any | None = None,
    ) -> None:
        self._providers: dict[str, LLMProvider] = {
            cfg.name: _build_provider(cfg) for cfg in providers
        }
        self._fallback = fallback_chain or list(self._providers)
        self._cache = _LRU()
        self._cache_lock = asyncio.Lock()
        self._failure_counts: dict[str, tuple[int, float]] = {}
        self._state_manager = state_manager
        # Health check cache: provider -> (is_healthy, timestamp)
        self._health_cache: dict[str, tuple[bool, float]] = {}
        self._health_cache_ttl: float = 30.0

    # ── Post-processing hook (R2-B: thinking-tag strip, R2: budget enforce) ─
    def _postprocess_llm_response(self, resp: LLMResponse, req: LLMRequest) -> LLMResponse:
        """Apply common post-processing to every provider-generated response.

        * Strips chain-of-thought tag wrappers (R2-B).
        * Raises :class:`ThinkingBudgetExhaustedError` if the usable answer
          fraction is below the regulated minimum (R2).

        The response object is mutated in place and also returned for chaining
        convenience.  The error message intentionally contains no raw model
        output (S-3 safety invariant).
        """
        # 1. Strip thinking tags and record them in reasoning_content if empty.
        clean, n_stripped, reasoning_text = _strip_thinking_tags(resp.content or "")
        if n_stripped > 0:
            _bump_stripped_metrics(n_stripped)
            resp.content = clean
            if not resp.reasoning_content and reasoning_text:
                resp.reasoning_content = reasoning_text
        # Derive usable answer token counts (fall back to char-based approx if provider omits).
        max_toks = max(int(getattr(req, "max_tokens", 0) or 0), 0)
        answer_len_chars = len((resp.content or "").strip())
        completion_explicit = int(resp.completion_tokens) or 0
        if completion_explicit <= 0:
            answer_tokens = _approx_tokens(resp.content or "")
        else:
            answer_tokens = completion_explicit
        reasoning_approx_toks = _approx_tokens(resp.reasoning_content or "")
        thinking_tokens = reasoning_approx_toks if reasoning_approx_toks > 0 else 0

        # 2. 思考预算守卫（生产事故修复）
        #    原始判据会误杀"答案本来就短"的合法回答：例如 max_tokens=2048、
        #    回答 47 token、且模型确实产出了 reasoning 时，ratio=2.3%<5% 且 47<=64，
        #    于是被判定为 thinking_budget_exhausted —— 实测这正是主力模型
        #    (ornith-1.5-9b/35b) 的常态输出形态，造成大批"假失败"。
        #    真实故障模式是"思考把预算吃光、答案近乎为空"，因此改为：
        #      * 答案确实**近乎为空**（<=8 token 或 content 为空白）；
        #      * 且确实发生过思考（thinking_tokens >= 50）。
        answer_nearly_empty = answer_tokens <= 8 or answer_len_chars == 0
        cond_a = answer_nearly_empty and thinking_tokens >= 50
        cond_b = (resp.completion_tokens or 0) > 0 and answer_len_chars == 0
        cond_c = False
        if cond_a or cond_b or cond_c:
            thinking_ratio = round(thinking_tokens / max(thinking_tokens + answer_tokens, 1), 3)
            msg = (
                "thinking_budget_exhausted: "
                f"answer_tok={answer_tokens} max_tok={max_toks} "
                f"thinking_tok={thinking_tokens} "
                f"cond_a={cond_a} cond_b={cond_b} cond_c={cond_c} "
                f"thinking_ratio={thinking_ratio}"
            )
            raise ThinkingBudgetExhaustedError(msg)
        return resp

    async def _check_health_cached(self, name: str) -> bool:
        """Cached health check for a provider (TTL 30s)."""
        now = time.monotonic()
        if name in self._health_cache:
            healthy, ts = self._health_cache[name]
            if now - ts < self._health_cache_ttl:
                return healthy
        try:
            healthy = await asyncio.wait_for(
                self._providers[name].health(), timeout=_HEALTH_CHECK_TIMEOUT_S
            )
        except Exception:
            healthy = False
        self._health_cache[name] = (healthy, now)
        return healthy

    def _apply_runtime_state(
        self, request: LLMRequest, provider: str | None
    ) -> tuple[str | None, LLMRequest]:
        """Merge provider-agnostic runtime overrides (temperature / max_tokens).

        重要：**不能**用 ``state.provider`` 覆盖未显式指定的 ``provider``。调用方随后
        以 ``chain = [provider] if provider else list(self._fallback)`` 构造链；一旦此处
        返回非 None，配置的兜底链会被塌缩成单 provider（历史事故：35B 超时后
        9B/ollama 兜底永不执行 → 成功率 0%）。

        模型(``state.model``)是 **provider 专属**的，必须逐 provider 解析，见
        :meth:`_resolve_request_for_provider`。
        """
        sm = self._state_manager
        if sm is None:
            return provider, request
        state = sm.get_state()
        if state.temperature is not None:
            request.temperature = state.temperature
        if state.max_tokens is not None and request.max_tokens > state.max_tokens:
            # 封顶（不抬高）：请求若本就更小则保留
            request.max_tokens = state.max_tokens
        return provider, request

    def _cap_max_tokens(self, request: LLMRequest) -> LLMRequest:
        """把输出预算封顶到 state.max_tokens（``MORE_LLM_MAX_TOKENS``）。

        ``generate_with_fallback_chain`` / ``generate_parallel`` 不经过
        ``_apply_runtime_state``，会绕过全局预算；L1 的 8192 预算因此直接打到慢
        模型上（历史：单次调用 130s+ 并拖垮任务）。这两个入口显式调用本方法。
        """
        sm = self._state_manager
        if sm is None:
            return request
        cap = sm.get_state().max_tokens
        if cap is not None and request.max_tokens > cap:
            request.max_tokens = cap
        return request

    def _resolve_request_for_provider(self, request: LLMRequest, provider: str) -> LLMRequest:
        """Resolve the effective model for ONE provider in the fallback chain.

        优先级：调用方显式 ``model_override`` > ``state.model``（仅当该 provider 就是
        ``state.provider`` 时）> provider 自身默认模型。这样把模型兜底到其它 provider
        时不会强行套用不存在的模型名（如把 LM Studio 模型名发给 ollama）。
        """
        if request.model_override:
            return request
        sm = self._state_manager
        if sm is None:
            return request
        state = sm.get_state()
        if state.model and (not state.provider or provider == state.provider):
            return self._create_request_with_model(request, state.model)
        return request

    def list_providers(self) -> list[str]:
        return list(self._providers)

    @staticmethod
    def _cache_key(req: LLMRequest, provider: str, model: str | None = None) -> str:
        raw = (
            f"{provider}|{model or ''}|{req.system or ''}|{req.prompt}|{req.temperature}"
            f"|{req.max_tokens}|{','.join(req.stop)}|{sorted(req.extra.items())}"
            f"|{req.model_override or ''}|{req.enable_thinking}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _create_request_with_model(self, request: LLMRequest, model: str | None) -> LLMRequest:
        """Create a new request with model override if provided."""
        if model:
            return LLMRequest(
                prompt=request.prompt,
                system=request.system,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stop=list(request.stop),
                extra=dict(request.extra),
                model_override=model,
                enable_thinking=request.enable_thinking,
            )
        return request

    def _should_skip(self, provider: str, model: str | None, threshold: int = 3) -> bool:
        """Check if provider/model should be skipped due to failures.

        Stale failures (older than ``_FAILURE_TTL_S``) are forgotten so a
        transient outage cannot disable a provider for the process lifetime.
        """
        key = f"{provider}:{model or 'default'}"
        item = self._failure_counts.get(key)
        if item is None:
            return False
        count, ts = item
        if time.monotonic() - ts > _FAILURE_TTL_S:
            del self._failure_counts[key]
            return False
        return count >= threshold

    def _record_failure(self, provider: str, model: str | None, error: str | None = None) -> None:
        """Record a failure for a provider/model pair.

        生产事故修复：模型**加载失败**（模型名不存在 / 引擎起不来）属于确定性故障，
        重试 3 次只会白烧 3 倍延迟。此类错误直接把计数拉到跳过阈值。
        """
        key = f"{provider}:{model or 'default'}"
        count = self._failure_counts.get(key, (0, 0.0))[0] + 1
        if error and _is_hard_model_failure(error):
            count = max(count, _HARD_FAILURE_THRESHOLD)
            _logger.warning("Hard model failure for %s (skip until TTL): %s", key, str(error)[:160])
        self._failure_counts[key] = (count, time.monotonic())
        _logger.warning(f"Failure recorded for {key}: {count}")

    def _record_success(self, provider: str, model: str | None) -> None:
        """Record a success, reset failure count."""
        key = f"{provider}:{model or 'default'}"
        self._failure_counts.pop(key, None)

    async def generate(
        self,
        request: LLMRequest,
        provider: str | None = None,
        model_override: str | None = None,
        use_cache: bool = True,
        contract_timeout_s: float | None = None,
    ) -> LLMResponse:
        """Generate LLM response with fallback chain.

        Args:
            request: LLM request with prompt, temperature, etc.
            provider: Specific provider to use, or None for fallback chain
            model_override: Override model name for this request
            use_cache: Whether to use response caching
            contract_timeout_s: P1-3 R4-B: 从 DeliverableContract.timeout_s 透传的
                任务级总超时；effective deadline = min(timeout - 5s, 90s)。默认 90s。

        Returns:
            LLMResponse with generated response

        Raises:
            LLMError: When all providers in fallback chain fail
        """
        if model_override:
            request = self._create_request_with_model(request, model_override)
            provider = provider or self._fallback[0] if self._fallback else None

        provider, request = self._apply_runtime_state(request, provider)

        chain = [provider] if provider else list(self._fallback)
        if provider is None and self._state_manager is not None:
            # state.provider 只作"偏好"：排链首，但**不删除**其它兜底 provider。
            _pref = self._state_manager.get_state().provider
            if _pref and _pref in chain:
                chain = [_pref] + [n for n in chain if n != _pref]
        last_exc: Exception | None = None
        effective_deadline_s = _effective_fallback_deadline(contract_timeout_s)
        deadline = time.monotonic() + effective_deadline_s
        # request_id is the stable grouping key across all fallback attempts
        # in this generate() call; each provider trial bumps attempt +=1.
        logical_rid = getattr(request, "id", "") or f"gen_{int(time.time() * 1e6)}"
        attempt = 0

        for _idx, name in enumerate(chain):
            if name not in self._providers:
                continue
            # 逐 provider 解析生效模型（state.model 是 provider 专属的）
            attempt_req = self._resolve_request_for_provider(request, name)
            if self._should_skip(name, attempt_req.model_override):
                _logger.info("Skipping %s due to repeated failures", name)
                continue
            # Quick health check before attempting (cached, TTL 30s)
            if not await self._check_health_cached(name):
                _logger.warning("Provider %s is unhealthy, skipping", name)
                continue

            key = self._cache_key(attempt_req, name, attempt_req.model_override)
            if use_cache:
                async with self._cache_lock:
                    cached = self._cache.get(key)
                    if cached is not None:
                        try:
                            from ..governance.observability import record_llm_call
                        except Exception:  # pragma: no cover
                            record_llm_call = None
                        if record_llm_call is not None:
                            record_llm_call(
                                request_id=logical_rid,
                                provider=cached.provider or name,
                                model=cached.model or attempt_req.model_override or "",
                                prompt_chars=len(request.prompt or ""),
                                prompt_tokens=cached.prompt_tokens,
                                completion_tokens=cached.completion_tokens,
                                latency_ms=0.0,
                                success=True,
                                cached=True,
                                attempt=attempt,
                                temperature=request.temperature,
                                max_tokens=request.max_tokens,
                            )
                        cached_resp = LLMResponse(
                            content=cached.content,
                            provider=cached.provider,
                            model=cached.model,
                            prompt_tokens=cached.prompt_tokens,
                            completion_tokens=cached.completion_tokens,
                            latency_ms=0.0,
                            cached=True,
                            reasoning_content=cached.reasoning_content,
                        )
                        return self._postprocess_llm_response(cached_resp, attempt_req)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _logger.error("Fallback chain total timeout exceeded (%ss)", effective_deadline_s)
                raise LLMError(
                    f"fallback chain total timeout exceeded after {effective_deadline_s}s"
                ) from last_exc
            # 预算公平分配：把剩余时间均摊给"剩余已注册 provider"，避免慢的首选
            # 吃光整条链预算、让兜底永远轮不到（此前 35B 超时 → 9B 兜底形同虚设）。
            remaining_providers = sum(1 for _n in chain[_idx:] if _n in self._providers)
            attempt_timeout = (
                remaining / remaining_providers if remaining_providers > 1 else remaining
            )
            try:
                start = time.perf_counter()
                resp = await asyncio.wait_for(
                    self._providers[name].generate(attempt_req), timeout=attempt_timeout
                )
                resp.latency_ms = (time.perf_counter() - start) * 1000
                resp = self._postprocess_llm_response(resp, attempt_req)
                self._record_success(name, attempt_req.model_override)
                if use_cache:
                    async with self._cache_lock:
                        self._cache.put(key, resp)
                try:
                    from ..governance.observability import record_llm_call
                except Exception:  # pragma: no cover
                    record_llm_call = None
                if record_llm_call is not None:
                    record_llm_call(
                        request_id=logical_rid,
                        provider=resp.provider or name,
                        model=resp.model or attempt_req.model_override or "",
                        prompt_chars=len(request.prompt or ""),
                        prompt_tokens=resp.prompt_tokens,
                        completion_tokens=resp.completion_tokens,
                        latency_ms=resp.latency_ms,
                        success=True,
                        cached=False,
                        attempt=attempt,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                    )
                return resp
            except asyncio.CancelledError:
                # R-11: 请求被外层 wait_for 取消（任务级超时）时也要留痕，
                # 否则超时故障在指标里表现为"没有调用"。
                self._emit_llm_call(
                    request_id=logical_rid,
                    provider=name,
                    model=attempt_req.model_override or "",
                    prompt_chars=len(request.prompt or ""),
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    success=False,
                    error="cancelled (task timeout / client disconnect)",
                    attempt=attempt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                raise
            except Exception as exc:
                _elapsed = (time.perf_counter() - start) * 1000
                self._record_failure(name, attempt_req.model_override, _exc_summary(exc, _elapsed))
                try:
                    from ..governance.observability import record_llm_call
                except Exception:  # pragma: no cover
                    record_llm_call = None
                if record_llm_call is not None:
                    record_llm_call(
                        request_id=logical_rid,
                        provider=name,
                        model=attempt_req.model_override or "",
                        prompt_chars=len(request.prompt or ""),
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=_elapsed,
                        success=False,
                        cached=False,
                        error=_exc_summary(exc, _elapsed)[:4000],
                        attempt=attempt,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                    )
                last_exc = exc
                _logger.warning(f"Provider {name} failed: {exc}")
                attempt += 1
                continue
        raise LLMError(f"all providers failed: {last_exc}") from last_exc

    @staticmethod
    def _emit_llm_call(
        *,
        request_id: str,
        provider: str,
        model: str,
        prompt_chars: int,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        success: bool,
        cached: bool = False,
        error: str = "",
        attempt: int = 0,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        """Emit one telemetry row for ANY LLM entry point.

        Historically only ``generate()`` was instrumented, so tasks that went
        through ``generate_with_fallback_chain`` / ``generate_parallel`` /
        ``stream`` produced **zero** runtime metrics.  Centralising the emit
        here keeps every path observable.
        """
        try:
            from ..governance.observability import record_llm_call
        except Exception:  # pragma: no cover - telemetry must never break the call
            return
        try:
            record_llm_call(
                request_id=request_id,
                provider=provider,
                model=model,
                prompt_chars=int(prompt_chars),
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                latency_ms=float(latency_ms),
                success=bool(success),
                cached=bool(cached),
                error=(error or "")[:4000],
                attempt=int(attempt),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception:  # pragma: no cover - defensive
            pass

    async def generate_with_fallback_chain(
        self,
        request: LLMRequest,
        chain: list[ProviderModelPair],
        use_cache: bool = True,
        contract_timeout_s: float | None = None,
    ) -> LLMResponse:
        """Generate with a complete fallback chain of provider-model pairs.

        Args:
            request: LLM request
            chain: List of (provider, model) pairs to try in order
            use_cache: Whether to use response caching
            contract_timeout_s: P1-3 R4-B: 从 DeliverableContract.timeout_s 透传。
                effective = min(timeout - 5s, 90s)。默认 90s。

        Returns:
            LLMResponse from first successful pair

        Raises:
            LLMError: When all pairs in chain fail
        """
        request = self._cap_max_tokens(request)
        last_exc: Exception | None = None
        effective_deadline_s = _effective_fallback_deadline(contract_timeout_s)
        deadline = time.monotonic() + effective_deadline_s
        chain_rid = f"chain_{int(time.time() * 1e6)}"
        chain_attempt = 0

        for pair in chain:
            if pair.provider not in self._providers:
                continue
            if self._should_skip(pair.provider, pair.model):
                _logger.info("Skipping %s/%s due to failures", pair.provider, pair.model)
                continue
            if not await self._check_health_cached(pair.provider):
                _logger.warning("Provider %s is unhealthy, skipping", pair.provider)
                continue

            req = self._create_request_with_model(request, pair.model)
            key = self._cache_key(req, pair.provider, pair.model)

            if use_cache:
                async with self._cache_lock:
                    cached = self._cache.get(key)
                    if cached is not None:
                        cached_resp = LLMResponse(
                            content=cached.content,
                            provider=cached.provider,
                            model=cached.model,
                            prompt_tokens=cached.prompt_tokens,
                            completion_tokens=cached.completion_tokens,
                            latency_ms=0.0,
                            cached=True,
                            reasoning_content=cached.reasoning_content,
                        )
                        self._emit_llm_call(
                            request_id=chain_rid,
                            provider=cached.provider or pair.provider,
                            model=cached.model or pair.model or "",
                            prompt_chars=len(request.prompt or ""),
                            prompt_tokens=cached.prompt_tokens,
                            completion_tokens=cached.completion_tokens,
                            latency_ms=0.0,
                            success=True,
                            cached=True,
                            attempt=chain_attempt,
                            temperature=request.temperature,
                            max_tokens=request.max_tokens,
                        )
                        return self._postprocess_llm_response(cached_resp, req)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _logger.error("Fallback chain total timeout exceeded (%ss)", effective_deadline_s)
                raise LLMError(
                    f"fallback chain total timeout exceeded after {effective_deadline_s}s"
                ) from last_exc
            try:
                start = time.perf_counter()
                resp = await asyncio.wait_for(
                    self._providers[pair.provider].generate(req), timeout=remaining
                )
                resp.latency_ms = (time.perf_counter() - start) * 1000
                resp = self._postprocess_llm_response(resp, req)
                self._record_success(pair.provider, pair.model)
                if use_cache:
                    async with self._cache_lock:
                        self._cache.put(key, resp)
                self._emit_llm_call(
                    request_id=chain_rid,
                    provider=resp.provider or pair.provider,
                    model=resp.model or pair.model or "",
                    prompt_chars=len(request.prompt or ""),
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    latency_ms=resp.latency_ms,
                    success=True,
                    attempt=chain_attempt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                return resp
            except asyncio.CancelledError:
                self._emit_llm_call(
                    request_id=chain_rid,
                    provider=pair.provider,
                    model=pair.model or "",
                    prompt_chars=len(request.prompt or ""),
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    success=False,
                    error="cancelled (task timeout / client disconnect)",
                    attempt=chain_attempt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                raise
            except Exception as exc:
                _elapsed = (time.perf_counter() - start) * 1000
                self._record_failure(pair.provider, pair.model, _exc_summary(exc, _elapsed))
                self._emit_llm_call(
                    request_id=chain_rid,
                    provider=pair.provider,
                    model=pair.model or "",
                    prompt_chars=len(request.prompt or ""),
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=_elapsed,
                    success=False,
                    error=_exc_summary(exc, _elapsed),
                    attempt=chain_attempt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                last_exc = exc
                chain_attempt += 1
                _logger.warning(f"{pair.provider}/{pair.model} failed: {exc}")
                continue

        raise LLMError(f"all fallback pairs failed: {last_exc}") from last_exc

    async def generate_parallel(
        self,
        request: LLMRequest,
        candidates: list[ProviderModelPair],
        use_cache: bool = True,
        timeout_s: float = 120.0,
    ) -> LLMResponse:
        """Race-to-first: send request to multiple providers simultaneously.

        All candidates are tried *in parallel*.  The first successful
        response wins; the remaining in-flight requests are cancelled.

        This is the key enabler for parallel-LLM architectures:
        - 2× 27B models on the same LM Studio instance → load balanced
        - LM Studio 27B + Ollama 7B → fast local fallback
        - LM Studio + DeepSeek cloud API → hybrid acceleration

        Args:
            request: LLM request
            candidates: List of (provider, model) pairs to race
            use_cache: Whether to check the LRU cache first
            timeout_s: Max wall-clock time before raising

        Returns:
            First successful LLMResponse

        Raises:
            LLMError: When all candidates fail
        """
        import asyncio as _aio

        request = self._cap_max_tokens(request)
        par_rid = f"par_{int(time.time() * 1e6)}"

        # 1. Filter to healthy, non-skipped candidates
        valid: list[tuple[ProviderModelPair, str]] = []  # (pair, cache_key)
        for pair in candidates:
            if pair.provider not in self._providers:
                continue
            if self._should_skip(pair.provider, pair.model):
                _logger.info(
                    "generate_parallel: skipping %s/%s (failures)", pair.provider, pair.model
                )
                continue
            if not await self._check_health_cached(pair.provider):
                _logger.warning("generate_parallel: skipping %s (unhealthy)", pair.provider)
                continue
            req = self._create_request_with_model(request, pair.model)
            cache_key = self._cache_key(req, pair.provider, pair.model)
            valid.append((pair, cache_key))

        if not valid:
            raise LLMError("generate_parallel: no healthy candidates")

        # 2. Cache hit → return immediately (no race needed)
        if use_cache:
            async with self._cache_lock:
                for pair, cache_key in valid:
                    cached = self._cache.get(cache_key)
                    if cached is not None:
                        _logger.debug(
                            "generate_parallel: cache hit %s/%s", pair.provider, pair.model
                        )
                        cached_resp = LLMResponse(
                            content=cached.content,
                            provider=cached.provider,
                            model=cached.model,
                            prompt_tokens=cached.prompt_tokens,
                            completion_tokens=cached.completion_tokens,
                            latency_ms=0.0,
                            cached=True,
                            reasoning_content=cached.reasoning_content,
                        )
                        req = self._create_request_with_model(request, pair.model)
                        self._emit_llm_call(
                            request_id=par_rid,
                            provider=cached.provider or pair.provider,
                            model=cached.model or pair.model or "",
                            prompt_chars=len(request.prompt or ""),
                            prompt_tokens=cached.prompt_tokens,
                            completion_tokens=cached.completion_tokens,
                            latency_ms=0.0,
                            success=True,
                            cached=True,
                            temperature=request.temperature,
                            max_tokens=request.max_tokens,
                        )
                        return self._postprocess_llm_response(cached_resp, req)

        # 3. Launch all in parallel, race to first success
        async def _try_one(pair: ProviderModelPair) -> LLMResponse:
            """Attempt one candidate.  Raises on failure."""
            req = self._create_request_with_model(request, pair.model)
            start = time.perf_counter()
            resp = await self._providers[pair.provider].generate(req)
            resp.latency_ms = (time.perf_counter() - start) * 1000
            return self._postprocess_llm_response(resp, req)

        par_start = time.perf_counter()
        tasks = {_aio.create_task(_try_one(p)): p for p, _ in valid}
        pending: set[_aio.Task[Any]] = set(tasks)
        errors: list[tuple[str, str, str]] = []

        try:
            done, pending = await _aio.wait(
                pending,
                timeout=timeout_s,
                return_when=_aio.FIRST_COMPLETED,
            )

            for task in done:
                pair = tasks[task]
                try:
                    resp: LLMResponse = task.result()
                    # Success!  Cache it and return.
                    self._record_success(pair.provider, pair.model)
                    if use_cache:
                        key = self._cache_key(
                            self._create_request_with_model(request, pair.model),
                            pair.provider,
                            pair.model,
                        )
                        async with self._cache_lock:
                            self._cache.put(key, resp)
                    self._emit_llm_call(
                        request_id=par_rid,
                        provider=resp.provider or pair.provider,
                        model=resp.model or pair.model or "",
                        prompt_chars=len(request.prompt or ""),
                        prompt_tokens=resp.prompt_tokens,
                        completion_tokens=resp.completion_tokens,
                        latency_ms=resp.latency_ms,
                        success=True,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                    )
                    _logger.info(
                        "generate_parallel: won race [%s/%s] in %.0fms",
                        pair.provider,
                        pair.model,
                        resp.latency_ms,
                    )
                    # Cancel remaining tasks; await them so no exception
                    # is left unretrieved and no task is destroyed pending.
                    for t in pending:
                        t.cancel()
                    await _aio.gather(*pending, return_exceptions=True)
                    return resp
                except BaseException as exc:
                    # 并行批次起点（_try_one 的 start 是嵌套局部变量，外层不可见）
                    _elapsed = (time.perf_counter() - par_start) * 1000
                    self._record_failure(pair.provider, pair.model, _exc_summary(exc, _elapsed))
                    self._emit_llm_call(
                        request_id=par_rid,
                        provider=pair.provider,
                        model=pair.model or "",
                        prompt_chars=len(request.prompt or ""),
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=_elapsed,
                        success=False,
                        error=_exc_summary(exc, _elapsed),
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                    )
                    errors.append((pair.provider, pair.model, str(exc)))
                    _logger.warning(
                        "generate_parallel: %s/%s failed: %s",
                        pair.provider,
                        pair.model,
                        exc,
                    )

            # If we get here, first-completed tasks all failed.
            # We still have pending tasks — keep waiting until a success,
            # all fail, or the remaining budget runs out.  A failure from
            # one candidate must NOT cancel still-running candidates that
            # could succeed (e.g. a slow-but-healthy fallback provider).
            deadline2 = time.monotonic() + max(0.1, timeout_s - 10)
            while pending:
                remaining2 = deadline2 - time.monotonic()
                if remaining2 <= 0:
                    break
                done2, pending = await _aio.wait(
                    pending,
                    timeout=remaining2,
                    return_when=_aio.FIRST_COMPLETED,
                )
                if not done2:
                    break
                for task in done2:
                    pair = tasks[task]
                    try:
                        resp = task.result()
                        self._record_success(pair.provider, pair.model)
                        if use_cache:
                            key = self._cache_key(
                                self._create_request_with_model(request, pair.model),
                                pair.provider,
                                pair.model,
                            )
                            async with self._cache_lock:
                                self._cache.put(key, resp)
                        _logger.info(
                            "generate_parallel: won race (later) [%s/%s]",
                            pair.provider,
                            pair.model,
                        )
                        for t in pending:
                            t.cancel()
                        await _aio.gather(*pending, return_exceptions=True)
                        return resp
                    except BaseException as exc:
                        self._record_failure(pair.provider, pair.model)
                        errors.append((pair.provider, pair.model, str(exc)))

            # All failed
            for t in pending:
                t.cancel()
                try:
                    await t
                except BaseException:
                    pass

        except _aio.TimeoutError:
            for t in pending:
                t.cancel()
            raise LLMError(
                f"generate_parallel: timeout after {timeout_s}s with {len(errors)} failures"
            )

        err_summary = "; ".join(f"{p}/{m}: {e[:80]}" for p, m, e in errors[:5])
        raise LLMError(
            f"generate_parallel: all {len(candidates)} candidates failed. Errors: {err_summary}"
        )

    async def stream(
        self,
        request: LLMRequest,
        provider: str | None = None,
        model_override: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens from the best available provider with fallback."""
        chain = [provider] if provider else list(self._fallback)
        deadline = time.monotonic() + _FALLBACK_DEADLINE_S
        stream_rid = f"stream_{int(time.time() * 1e6)}"
        stream_attempt = 0
        for name in chain:
            if name not in self._providers or self._should_skip(name, model_override):
                continue
            started = time.perf_counter()
            emitted_chars = 0
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LLMError("stream fallback chain total timeout exceeded")
                # wait_for around each anext() bounds idle reads; the
                # shrinking `remaining` budget bounds the whole stream.
                stream_iter = await self._providers[name].stream(request)
                while True:
                    try:
                        token = await asyncio.wait_for(anext(stream_iter), timeout=remaining)
                    except StopAsyncIteration:
                        break
                    yield token
                    emitted_chars += len(token or "")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LLMError("stream fallback chain total timeout exceeded")
                self._record_success(name, model_override)
                self._emit_llm_call(
                    request_id=stream_rid,
                    provider=name,
                    model=model_override or "",
                    prompt_chars=len(request.prompt or ""),
                    prompt_tokens=0,
                    completion_tokens=max(1, emitted_chars // 4),
                    latency_ms=(time.perf_counter() - started) * 1000,
                    success=True,
                    attempt=stream_attempt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                return
            except asyncio.CancelledError:
                self._emit_llm_call(
                    request_id=stream_rid,
                    provider=name,
                    model=model_override or "",
                    prompt_chars=len(request.prompt or ""),
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    success=False,
                    error="cancelled (task timeout / client disconnect)",
                    attempt=stream_attempt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                raise
            except Exception as exc:
                _stream_elapsed = (time.perf_counter() - started) * 1000
                self._record_failure(name, model_override, _exc_summary(exc, _stream_elapsed))
                self._emit_llm_call(
                    request_id=stream_rid,
                    provider=name,
                    model=model_override or "",
                    prompt_chars=len(request.prompt or ""),
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=_stream_elapsed,
                    success=False,
                    error=_exc_summary(exc, _stream_elapsed),
                    attempt=stream_attempt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                stream_attempt += 1
                _logger.warning(f"Stream from {name} failed: {exc}")
                continue
        raise LLMError("all providers failed streaming")

    async def health(self) -> dict[str, bool]:
        """Check health status of all providers."""
        return {name: await p.health() for name, p in self._providers.items()}

    def get_failure_counts(self) -> dict[str, int]:
        """Get failure counts for monitoring."""
        return {k: count for k, (count, _) in self._failure_counts.items()}

    def reset_failure_counts(self) -> None:
        """Reset all failure counts (e.g., after system recovery)."""
        self._failure_counts.clear()
        _logger.info("All failure counts reset")

    async def close(self) -> None:
        """Close all provider connection pools for graceful shutdown."""
        for provider in self._providers.values():
            if hasattr(provider, "close"):
                try:
                    await provider.close()
                except Exception as exc:
                    _logger.warning("Error closing provider: %s", exc)
