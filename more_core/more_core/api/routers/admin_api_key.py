"""Admin router — API key management plane.

Endpoints
---------
``POST   /api/v1/admin/api-key``                     issue a scoped, expiring key
``GET    /api/v1/admin/api-key``                     list keys (never the secret)
``POST   /api/v1/admin/api-key/{key_id}/rotate``     rotate with optional grace
``POST   /api/v1/admin/api-key/{key_id}/revoke``     immediate revocation
``POST   /api/v1/admin/api-key/purge``               drop expired/revoked rows
``POST   /api/v1/admin/api-key/rotate``              legacy single-key env rotation

Notes
-----
* Every endpoint requires the ``admin:apikeys`` scope (or the wildcard key).
* The raw secret is returned **once**, at issue/rotate time; the store keeps
  only ``HMAC-SHA256(pepper, key)``.
* ``write_env_file`` (legacy rotation) is confined to an allow-list: the
  repository's own ``more_core/.env`` plus any directory listed in
  ``MORE_ENV_WRITE_ALLOWLIST`` (``os.pathsep``-separated).
* ``rotation_proof`` is now **mandatory** for the legacy rotation endpoint —
  a missing/invalid proof is rejected instead of silently self-signed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_scope
from ...security.api_key_ops import (
    inject_api_key_into_env,
    validate_api_key_report,
    verify_rotation_proof,
)

ADMIN_SCOPE = "admin:apikeys"

_DISABLED_MSG = (
    "legacy env rotation disabled: set MORE_MASTER_ROTATION_KEY (>=32 chars) in the "
    "server environment, sign a proof with `more-os api-key rotate-proof`, then retry."
)

#: Directories that ``write_env_file`` may target in addition to the repo .env.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_WRITABLE = (_REPO_ROOT / "more_core" / ".env",)


class IssueRequest(BaseModel):
    label: str = Field(default="", max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["tasks:execute"])
    ttl_days: float | None = Field(default=None, ge=0, le=3650)
    ttl_seconds: int | None = Field(default=None, ge=0, le=315_360_000)
    # 分派归属（谁在用这把钥匙）
    owner: str = Field(default="", max_length=120, description="归属团队/租户")
    consumer: str = Field(default="", max_length=120, description="使用方服务名")
    purpose: str = Field(default="", max_length=200)
    channel: str = Field(default="", max_length=60, description="分发渠道，如 cli/api/secret-manager")
    # 使用管理
    quota_per_min: int | None = Field(default=None, ge=1, le=1_000_000)


class DispatchItem(BaseModel):
    owner: str = Field(default="", max_length=120)
    consumer: str = Field(default="ci", max_length=120)
    label: str = Field(default="", max_length=120)
    purpose: str = Field(default="", max_length=200)
    scopes: list[str] | None = None
    ttl_seconds: int | None = Field(default=None, ge=0, le=315_360_000)
    quota_per_min: int | None = Field(default=None, ge=1, le=1_000_000)


class DispatchRequest(BaseModel):
    assignments: list[DispatchItem] = Field(min_length=1, max_length=100)
    default_scopes: list[str] = Field(default_factory=lambda: ["tasks:execute"])
    default_ttl_seconds: int | None = Field(default=None, ge=0, le=315_360_000)
    channel: str = Field(default="api", max_length=60)


class RotateKeyRequest(BaseModel):
    grace_seconds: int = Field(default=3600, ge=0, le=30 * 24 * 3600)
    ttl_days: float | None = Field(default=None, ge=0, le=3650)


class LegacyRotateRequest(BaseModel):
    new_key: str | None = Field(
        default=None,
        description="留空则服务端生成 modern 格式密钥（sk-more-os- 前缀）。",
    )
    revoke_old_in_seconds: int = Field(ge=60, le=7 * 24 * 3600, default=3600)
    rotation_proof: str = Field(
        description="由 `more-os api-key rotate-proof` 用 MORE_MASTER_ROTATION_KEY 签名的 HMAC proof。",
    )
    strict: bool = Field(default=False)
    write_env_file: str | None = Field(
        default=None,
        description="可选：写入允许目录内的 .env；留空时仅返回新密钥 payload。",
    )


def _store() -> Any:
    from ...security.api_key_store import get_default_store

    try:
        return get_default_store()
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=503, detail=f"API key store unavailable: {exc}") from exc


def _writable_roots() -> list[Path]:
    roots: list[Path] = []
    extra = os.getenv("MORE_ENV_WRITE_ALLOWLIST", "")
    for raw in extra.split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw.strip()).expanduser().resolve())
    for default in _DEFAULT_WRITABLE:
        roots.append(default.resolve())
    return roots


def _assert_writable(path: str) -> Path:
    """Reject writes outside the configured allow-list (no arbitrary-path writes)."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="write_env_file must be an absolute path")
    resolved = target.resolve()
    for allowed in _writable_roots():
        if resolved == allowed or allowed in resolved.parents:
            return resolved
    raise HTTPException(
        status_code=400,
        detail=(
            "write_env_file is outside the allow-list; add its directory to "
            "MORE_ENV_WRITE_ALLOWLIST to permit it"
        ),
    )


def _issue_payload(raw_key: str, record: Any) -> dict[str, Any]:
    """Single place that returns a secret — callers must not log the result."""
    return {
        "status": "issued",
        "api_key": raw_key,
        "key": record.as_dict(),
        "warning": "store this key now — it is shown only once",
    }


def create_router(require_api_key: Callable[..., Any]) -> APIRouter:
    admin_deps = [Depends(require_api_key), Depends(require_scope(ADMIN_SCOPE))]
    router = APIRouter(prefix="/api/v1/admin", tags=["Admin"], dependencies=admin_deps)

    # -- managed-key lifecycle -------------------------------------------

    @router.post("/api-key")
    async def issue_api_key(payload: IssueRequest) -> dict[str, Any]:
        """Issue a new scoped key. The raw secret is returned exactly once."""
        ttl = payload.ttl_seconds
        if ttl is None and payload.ttl_days is not None:
            ttl = int(payload.ttl_days * 86400)
        raw, record = _store().register(
            label=payload.label,
            scopes=payload.scopes,
            ttl_seconds=ttl,
            owner=payload.owner,
            consumer=payload.consumer,
            purpose=payload.purpose,
            issued_by="admin-api",
            channel=payload.channel or "api",
            quota_per_min=payload.quota_per_min,
        )
        return _issue_payload(raw, record)

    @router.get("/api-key")
    async def list_api_keys(include_inactive: bool = True) -> dict[str, Any]:
        """List key metadata (id/prefix/scopes/expiry) — never the secret."""
        keys = _store().list_keys(include_inactive=include_inactive)
        return {"keys": [rec.as_dict() for rec in keys], "stats": _store().stats()}

    @router.post("/api-key/purge")
    async def purge_api_keys(older_than_seconds: int = 0) -> dict[str, Any]:
        removed = _store().purge_expired(older_than_seconds=older_than_seconds)
        return {"status": "purged", "removed": removed}

    @router.post("/api-key/dispatch")
    async def dispatch_api_keys(payload: DispatchRequest) -> dict[str, Any]:
        """批量分派：一次为多个消费方签发独立密钥（各自归属/作用域/配额）。

        明文仅在本次响应的 ``dispatched[].api_key`` 中出现一次，请立即分发到
        各消费方的密钥存储；后续无法再次取回。
        """
        store = _store()
        items = [item.model_dump() for item in payload.assignments]
        results = store.dispatch_batch(
            items,
            default_scopes=payload.default_scopes,
            default_ttl_seconds=payload.default_ttl_seconds,
            issued_by="admin-api",
            channel=payload.channel,
        )
        return {
            "status": "dispatched",
            "count": len(results),
            "channel": payload.channel,
            "dispatched": results,
            "warning": "store each key now — plaintext is shown only once",
        }

    @router.get("/api-key/usage/overview")
    async def api_key_usage_overview(window_s: int = 86400, top: int = 20) -> dict[str, Any]:
        """按密钥聚合的用量总览（分派后的使用管理视图）。"""
        return {"status": "ok", "overview": _store().usage_overview(window_s=window_s, top=top)}

    @router.get("/api-key/attention")
    async def api_key_attention(expiry_days: int = 14, stale_days: int = 30) -> dict[str, Any]:
        """需要人工关注：即将过期 / 从未使用 / 已过期未清理。"""
        return {"status": "ok", "attention": _store().attention(
            expiry_days=expiry_days, stale_days=stale_days)}

    @router.post("/api-key/usage/prune")
    async def api_key_usage_prune(keep_days: int = 7) -> dict[str, Any]:
        """裁剪逐次调用明细（保留聚合计数）。"""
        removed = _store().prune_usage(keep_days=keep_days)
        return {"status": "pruned", "removed": removed, "keep_days": keep_days}

    @router.get("/api-key/{key_id}/usage")
    async def api_key_usage(key_id: str, window_s: int = 86400) -> dict[str, Any]:
        """单把密钥的用量报表：调用量/失败/延迟/tokens/端点分布/按小时。"""
        store = _store()
        if store.get(key_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown key_id {key_id!r}")
        return {"status": "ok", "usage": store.usage(key_id, window_s=window_s)}

    @router.post("/api-key/{key_id}/rotate")
    async def rotate_api_key(key_id: str, payload: RotateKeyRequest) -> dict[str, Any]:
        """Rotate a key; the old one stays valid for ``grace_seconds``."""
        ttl = int(payload.ttl_days * 86400) if payload.ttl_days is not None else None
        result = _store().rotate(
            key_id, grace_seconds=payload.grace_seconds, ttl_seconds=ttl
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"unknown key_id {key_id!r}")
        raw, record = result
        body = _issue_payload(raw, record)
        body["status"] = "rotated"
        body["old_key_grace_seconds"] = payload.grace_seconds
        return body

    @router.post("/api-key/{key_id}/revoke")
    async def revoke_api_key(key_id: str) -> dict[str, Any]:
        """Revoke a key immediately (effective on the next request)."""
        if not _store().revoke(key_id):
            raise HTTPException(
                status_code=404, detail=f"unknown or already-revoked key_id {key_id!r}"
            )
        return {"status": "revoked", "key_id": key_id}

    # -- legacy single-key env rotation -----------------------------------

    @router.post("/api-key/rotate")
    async def rotate_env_api_key(payload: LegacyRotateRequest) -> dict[str, Any]:
        """Rotate the legacy ``MORE_API_KEY`` env value, proof-gated.

        Requires ``MORE_MASTER_ROTATION_KEY`` plus a matching ``rotation_proof``;
        writes (when requested) are confined to the allow-list.
        """
        from ...security.api_key_ops import generate_api_key

        master_key = os.getenv("MORE_MASTER_ROTATION_KEY", "")
        if len(master_key) < 32:
            raise HTTPException(status_code=503, detail=_DISABLED_MSG)

        new_key = payload.new_key or generate_api_key(
            strength="modern", enforce_prefix=payload.strict
        )
        report = validate_api_key_report(new_key, require_prefix=payload.strict)
        if not report.valid:
            raise HTTPException(
                status_code=400,
                detail={"msg": "new_key failed validation", "errors": report.errors},
            )

        if not verify_rotation_proof(
            master_key=master_key,
            proof=payload.rotation_proof,
            new_key=new_key,
            revoke_old_in_seconds=payload.revoke_old_in_seconds,
        ):
            raise HTTPException(
                status_code=401, detail="rotation_proof signature invalid or expired"
            )

        wrote_path: str | None = None
        warnings: list[str] = []
        if payload.write_env_file:
            target = _assert_writable(payload.write_env_file)
            env_written, _backup, _prev = inject_api_key_into_env(
                new_key, str(target), backup=True, strict=payload.strict
            )
            wrote_path = str(env_written)
            warnings.append(
                "the running server keeps the old key until restart; hot-swap the "
                "env key via the managed-key endpoints instead"
            )

        return {
            "status": "rotated",
            "new_key_prefix": new_key[:10] + "***",
            "new_key_length": len(new_key),
            "revoke_old_in_seconds": payload.revoke_old_in_seconds,
            "wrote_env_file": wrote_path,
            "warnings": warnings,
        }

    return router
