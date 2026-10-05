"""Delivery router — 交付台账 / 成功率 / 全链路追溯。

对应三大硬伤中的"交付可信度"对外接口：

* ``GET /api/v1/delivery/stats``    交付成功率量化模型（按任务类型/时间窗）
* ``GET /api/v1/delivery/ledger``   最近交付明细（状态/版本/哈希/裁决/闸门）
* ``GET /api/v1/delivery/{task_id}`` 单个任务的全部交付版本（可追溯/可 diff）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Delivery"])
    deps = [Depends(require_api_key)] if require_api_key else []

    def _ledger() -> Any:
        from ...codegen.delivery_ledger import get_default_ledger

        return get_default_ledger()

    @router.get("/delivery/stats", dependencies=deps)
    async def delivery_stats(window_s: int = 86400) -> dict[str, Any]:
        """交付成功率量化模型。"""
        ledger = _ledger()
        return {
            "status": "ok",
            "stats": ledger.stats(window_s),
            # A-3：双窗口 + 趋势，避免历史故障期样本污染"当前状态"判断
            "windows": ledger.stats_windows(),
            "ledger_db": str(ledger.db_path),
            "last_error": ledger.last_error,
        }

    @router.get("/delivery/ledger", dependencies=deps)
    async def delivery_ledger(limit: int = 50, task_id: str | None = None) -> dict[str, Any]:
        """最近交付明细（可按 task_id 过滤）。"""
        rows = _ledger().list(task_id=task_id, limit=max(1, min(int(limit), 500)))
        return {"status": "ok", "count": len(rows), "deliveries": [r.to_dict() for r in rows]}

    @router.get("/delivery/{task_id}", dependencies=deps)
    async def delivery_for_task(task_id: str, limit: int = 20) -> dict[str, Any]:
        """某任务的全部交付版本（版本管理 / 全链路追溯）。"""
        rows = _ledger().list(task_id=task_id, limit=max(1, min(int(limit), 200)))
        if not rows:
            raise HTTPException(status_code=404, detail=f"no delivery records for {task_id!r}")
        return {
            "status": "ok",
            "task_id": task_id,
            "versions": len(rows),
            "deliveries": [r.to_dict() for r in rows],
        }

    return router
