"""LLM 链路预检 —— 在启动时暴露"模型名写错 / 兜底链断掉"这类静默故障。

背景（生产效率事故）：
    * ``MORE_LMSTUDIO_MODEL=local-model`` 是占位符，模型不存在 → 该模型 0% 成功；
    * ``MORE_OLLAMA_ENDPOINT`` 未配置 → Ollama provider 根本没注册 →
      声明的 ``lmstudio,ollama`` 兜底链实际是断的，主 provider 一挂就全线失败。

这两类问题此前**没有任何告警**，只能靠事后翻日志。本模块提供启动预检 +
``/api/v1/llm/preflight`` 端点，把配置问题在启动时就喊出来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

__all__ = ["ProviderCheck", "LLMPreflight", "preflight_llm"]

_TIMEOUT = 5.0


@dataclass
class ProviderCheck:
    name: str
    registered: bool
    endpoint: str = ""
    configured_model: str = ""
    models_available: int = 0
    model_present: bool | None = None  # None = 无法判定（provider 不支持列举）
    healthy: bool | None = None
    inference_ok: bool | None = None  # None = 未探测（默认关闭推理探针）
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "registered": self.registered,
            "endpoint": self.endpoint,
            "configured_model": self.configured_model,
            "models_available": self.models_available,
            "model_present": self.model_present,
            "healthy": self.healthy,
            "inference_ok": self.inference_ok,
            "warnings": list(self.warnings),
        }


@dataclass
class LLMPreflight:
    providers: list[ProviderCheck] = field(default_factory=list)
    fallback_chain: list[str] = field(default_factory=list)
    chain_registered: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # 生效模型：每次请求实际使用的 provider/model 来自 state manager，
    # 可能与 provider 自身配置不同（配置漂移 → 静默 400）。
    state_provider: str = ""
    state_model: str = ""
    state_model_present: bool | None = None

    @property
    def ok(self) -> bool:
        return not self.warnings

    @property
    def degraded(self) -> bool:
        """兜底层不足（只有单 provider 可用）。"""
        return len(self.chain_registered) < 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "degraded": self.degraded,
            "fallback_chain": list(self.fallback_chain),
            "chain_registered": list(self.chain_registered),
            "warnings": list(self.warnings),
            "state_provider": self.state_provider,
            "state_model": self.state_model,
            "state_model_present": self.state_model_present,
            "providers": [p.to_dict() for p in self.providers],
        }


def _model_matches(configured: str, served: str) -> bool:
    """LM Studio 同一模型可能有多个量化后缀，做归一化比较。"""
    return served == configured or served.startswith(configured + "-") or configured in served


def _list_models_endpoint(name: str, endpoint: str) -> str | None:
    base = (endpoint or "").rstrip("/")
    if not base:
        return None
    if name == "ollama" or "11434" in base:
        return base + "/api/tags"
    return base + "/models"


async def _fetch_models(url: str) -> list[str] | None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:
        return None
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):  # OpenAI 兼容
            return [str(m.get("id", "")) for m in data["data"]]
        if isinstance(data.get("models"), list):  # Ollama
            return [str(m.get("name", "")) for m in data["models"]]
    return None


async def preflight_llm(
    llm: Any,
    chain: list[str] | None = None,
    *,
    probe_inference: bool = False,
) -> LLMPreflight:
    """检查已注册 provider 的连通性、模型存在性与兜底链覆盖度。

    ``probe_inference=True`` 时额外发一个最小补全请求。原因：``health()`` 只探
    ``/models``（200 也可能推理 500），无法代表"能否真正出 token"。默认关闭
    以免拖慢启动；按需深度体检走 ``/api/v1/llm/preflight?probe=1``。
    """
    report = LLMPreflight()
    registered = list(llm.list_providers()) if llm is not None else []
    report.fallback_chain = list(chain or getattr(llm, "_fallback", []) or [])
    report.chain_registered = [p for p in report.fallback_chain if p in registered]

    models_by_provider: dict[str, list[str]] = {}
    if not registered:
        report.warnings.append("no LLM provider registered at all")
        return report

    for name in registered:
        provider = getattr(llm, "_providers", {}).get(name)
        if provider is None:
            report.warnings.append(f"provider {name} registered but instance missing")
            continue
        endpoint = str(
            getattr(provider, "_base", "")
            or getattr(provider, "_endpoint", "")
            or getattr(provider, "endpoint", "")
            or ""
        )
        model = str(getattr(provider, "model", "") or getattr(provider, "_model", "") or "")
        check = ProviderCheck(name=name, registered=True, endpoint=endpoint, configured_model=model)
        try:
            check.healthy = bool(await provider.health())
        except Exception:
            check.healthy = False
        if not check.healthy:
            check.warnings.append(f"provider {name} health check failed")

        if probe_inference:
            try:
                from .provider import LLMRequest

                resp = await provider.generate(LLMRequest(prompt="ping", max_tokens=1))
                check.inference_ok = resp is not None
            except Exception as exc:  # noqa: BLE001 - 探针失败即判定不可推理
                check.inference_ok = False
                check.warnings.append(f"inference probe failed: {exc}")
            if check.inference_ok is False and not any(
                w.startswith("inference probe failed") for w in check.warnings
            ):
                check.warnings.append("inference probe returned no response")

        url = _list_models_endpoint(name, endpoint)
        if url:
            models = await _fetch_models(url)
            if models is None:
                check.warnings.append(f"cannot list models from {url}")
            else:
                check.models_available = len(models)
                models_by_provider[name] = models
                if model:
                    check.model_present = any(_model_matches(model, m) for m in models)
                    if not check.model_present:
                        check.warnings.append(
                            f"configured model {model!r} not found among "
                            f"{len(models)} models served by {name} — requests will fail"
                        )
        report.warnings.extend(f"[{name}] {w}" for w in check.warnings)
        report.providers.append(check)

    # 生效模型检查：state manager 的 model 才是每次请求真正发送的标识。
    try:
        from .state_manager import get_llm_state_manager

        st = get_llm_state_manager().get_state()
        report.state_provider = str(getattr(st, "provider", "") or "")
        report.state_model = str(getattr(st, "model", "") or "")
        if report.state_model:
            served = models_by_provider.get(report.state_provider)
            if served is not None:
                report.state_model_present = any(
                    _model_matches(report.state_model, m) for m in served
                )
                if not report.state_model_present:
                    report.warnings.append(
                        f"[state] effective model {report.state_model!r} "
                        f"(provider {report.state_provider!r}) not found among "
                        f"{len(served)} served models — per-request calls will fail"
                    )
    except Exception:  # pragma: no cover - state check must never break preflight
        pass

    if report.degraded:
        report.warnings.append(
            f"fallback chain is degraded: only {report.chain_registered} registered "
            f"(declared: {report.fallback_chain})"
        )
    return report
