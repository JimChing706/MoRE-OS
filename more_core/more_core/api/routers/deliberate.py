"""Council deliberation router — multi-perspective cognitive debate endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.post("/deliberate", dependencies=[Depends(require_api_key)])
    async def deliberate(body: dict[str, Any]) -> dict[str, Any]:
        question = body.get("question", "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="question is required")

        council = getattr(core, "council_orchestrator", None)
        if council is None:
            raise HTTPException(
                status_code=503,
                detail="Council orchestrator not available (no LLM provider configured)",
            )

        scene_label = body.get("scene_label", "general")
        mode = body.get("mode", "standard")
        matched_keywords = body.get("matched_keywords")

        result = await council.deliberate(
            question=question,
            scene_label=scene_label,
            mode=mode,
            matched_keywords=matched_keywords,
        )

        return {
            "session_id": result.session_id,
            "question": result.question,
            "scene_label": result.scene_label,
            "mode": result.mode,
            "independent_outputs": result.independent_outputs,
            "cross_review_outputs": result.cross_review_outputs,
            "synthesis": result.synthesis,
            "errors": result.errors,
            "core_conclusion": result.core_conclusion,
            "consensus_level": result.consensus_level,
        }

    @router.post("/deliberate/quick", dependencies=[Depends(require_api_key)])
    async def deliberate_quick(body: dict[str, Any]) -> dict[str, Any]:
        question = body.get("question", "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="question is required")

        council = getattr(core, "council_orchestrator", None)
        if council is None:
            raise HTTPException(
                status_code=503,
                detail="Council orchestrator not available",
            )

        result = await council.deliberate(
            question=question,
            scene_label=body.get("scene_label", "general"),
            mode="quick",
            matched_keywords=body.get("matched_keywords"),
        )

        return {
            "session_id": result.session_id,
            "core_conclusion": result.core_conclusion,
            "consensus_level": result.consensus_level,
            "synthesis": result.synthesis,
            "errors": result.errors,
        }

    return router
