"""请求主体（principal）上下文 — 让身份来自凭证，而不是客户端请求体。

背景（RESIDUAL_RISKS R-03）：执行身份原先取自 ``request.context["actor"]``，
而该字段完全由调用方提供，于是调用方自报 ``actor = <管理员>`` 即可被采信，
配合"未配置 admin_users 时 RBAC 全放行"构成越权/冒充面。

修复思路：API 鉴权依赖在验证凭证后把**凭证派生**的主体写入 contextvar，
编排层只信任 contextvar；客户端提供的 actor 仅作为审计参考保留在
``context["requested_actor"]``，不再参与任何权限判断。
"""

from __future__ import annotations

from contextvars import ContextVar

__all__ = [
    "ANONYMOUS",
    "ENV_KEY_PRINCIPAL",
    "get_principal",
    "principal_from_api_key_id",
    "reset_principal",
    "set_principal",
]

ANONYMOUS = "anonymous"
#: 遗留 env 主密钥（MORE_API_KEY）对应的主体标识。
ENV_KEY_PRINCIPAL = "env-key-principal"

_principal: ContextVar[str] = ContextVar("more_principal", default="")


def principal_from_api_key_id(api_key_id: str | None) -> str:
    """Map an authenticated API-key id to a stable principal name."""
    if not api_key_id:
        return ANONYMOUS
    if api_key_id == "env:MORE_API_KEY":
        return ENV_KEY_PRINCIPAL
    return f"apikey:{api_key_id}"


def set_principal(name: str) -> None:
    _principal.set(name or "")


def get_principal() -> str:
    return _principal.get() or ""


def reset_principal() -> None:
    _principal.set("")
