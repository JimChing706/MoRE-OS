"""Import Task Document router — parse, validate, import, generate, templates.

Follows the same pattern as requirements.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from ...core.import_task import (
    ImportTaskDocument,
    ImportTaskGenerator,
    ImportTaskParser,
    ResourceBudget,
)
from ...runtime.orchestrator import MoRECore
from .tasks import _task_store


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    parser = ImportTaskParser()
    generator = ImportTaskGenerator()

    @router.post("/tasks/itd/parse", dependencies=[Depends(require_api_key)])
    async def parse_itd(content: dict[str, str]) -> dict[str, Any]:
        markdown = content.get("content", "")
        if not markdown:
            return {"error": "No content provided", "status": "failed"}
        try:
            doc = parser.parse(markdown)
            return {
                "status": "success",
                "document": doc.to_dict(),
                "warnings": doc._raw_frontmatter.get("_warnings", []),
            }
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    @router.post("/tasks/itd/validate")
    async def validate_itd(content: dict[str, str]) -> dict[str, Any]:
        markdown = content.get("content", "")
        if not markdown:
            return {"error": "No content provided", "status": "failed"}
        try:
            doc = parser.parse(markdown)
            warnings: list[str] = doc._raw_frontmatter.get("_warnings", [])
            return {
                "status": "success",
                "valid": True,
                "issues": [{"type": "warning", "message": w} for w in warnings],
                "summary": {
                    "total_warnings": len(warnings),
                    "requirements": len(doc.requirements),
                    "kill_criteria": len(doc.kill_criteria),
                    "acceptance_criteria": len(doc.contract_acceptance_criteria),
                },
            }
        except Exception as e:
            return {"error": str(e), "status": "failed", "valid": False}

    @router.post("/tasks/itd/import", dependencies=[Depends(require_api_key)])
    async def import_itd(content: dict[str, Any]) -> dict[str, Any]:
        markdown = content.get("content", "")
        auto_start = bool(content.get("auto_start", False))
        if not markdown:
            return {"error": "No content provided", "status": "failed"}
        try:
            doc = parser.parse(markdown)
            req = doc.to_task_request()

            task_id = req.id
            _task_store.create_task(
                task_id,
                {
                    "task_id": task_id,
                    "title": doc.title,
                    "type": doc.type,
                    "priority": doc.priority,
                    "description": doc.summary[:500],
                    "requirement_count": len(doc.requirements),
                    "status": "in_progress" if auto_start else "pending",
                    "progress": 0,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            result_data: dict[str, Any] = {
                "task_id": task_id,
                "title": doc.title,
                "type": doc.type,
                "status": "pending" if not auto_start else "running",
            }

            if auto_start:
                result = await core.execute(req)
                _task_store.update_task(
                    task_id,
                    {
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "result": result.output,
                        "progress": 100,
                    },
                )
                result_data.update(
                    {
                        "status": "completed",
                        "result": result.output,
                        "deliverable_complete": result.deliverable_complete,
                        "deliverable_missing": result.deliverable_missing,
                    }
                )

            return {
                "status": "success",
                "task": result_data,
                "warnings": doc._raw_frontmatter.get("_warnings", []),
            }
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    @router.get("/tasks/itd/templates")
    async def get_itd_templates() -> dict[str, Any]:
        templates = []

        # Code generation template
        code_doc = ImportTaskDocument(
            title="[Task Title]",
            version="1.0.0",
            author="[Author]",
            created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            type="code_generation",
            priority="medium",
            deliverable_kind="code",
            tags=["code"],
            summary="TODO: describe the task goal",
            contract_kind="code",
            contract_required_dimensions=["core_output", "reasoning", "tests"],
            contract_min_output_length=100,
            budget=ResourceBudget(estimated_tokens=4000, estimated_duration_min=15),
        )
        templates.append(
            {
                "id": "code",
                "name": "Code Generation",
                "description": "Feature implementation or bug fix task",
                "template": generator.generate(code_doc),
            }
        )

        # Architecture design template
        arch_doc = ImportTaskDocument(
            title="[Architecture Title]",
            version="1.0.0",
            author="[Author]",
            created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            type="architecture_design",
            priority="high",
            deliverable_kind="architecture",
            tags=["architecture"],
            summary="TODO: describe the architecture task",
            contract_kind="architecture",
            contract_required_dimensions=[
                "core_output",
                "reasoning",
                "risks",
                "alternatives",
            ],
            contract_min_output_length=200,
            budget=ResourceBudget(estimated_tokens=8000, estimated_duration_min=60),
        )
        templates.append(
            {
                "id": "architecture",
                "name": "Architecture Design",
                "description": "System architecture or component design task",
                "template": generator.generate(arch_doc),
            }
        )

        # Analysis template
        analysis_doc = ImportTaskDocument(
            title="[Analysis Title]",
            version="1.0.0",
            author="[Author]",
            created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            type="data_analysis",
            priority="medium",
            deliverable_kind="analysis",
            tags=["analysis"],
            summary="TODO: describe the analysis task",
            contract_kind="analysis",
            contract_required_dimensions=["core_output", "reasoning", "risks"],
            contract_min_output_length=100,
            budget=ResourceBudget(estimated_tokens=3000, estimated_duration_min=20),
        )
        templates.append(
            {
                "id": "analysis",
                "name": "Data Analysis",
                "description": "Data analysis, research, or investigation task",
                "template": generator.generate(analysis_doc),
            }
        )

        return {"status": "success", "templates": templates}

    @router.post("/tasks/itd/generate", dependencies=[Depends(require_api_key)])
    async def generate_itd(data: dict[str, Any]) -> dict[str, Any]:
        try:
            doc = ImportTaskDocument(
                title=data.get("title", "Untitled"),
                version=str(data.get("version", "1.0.0")),
                author=str(data.get("author", "")),
                created=data.get(
                    "created", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                ),
                type=str(data.get("type", "nlp_task")),
                priority=str(data.get("priority", "medium")),
                deliverable_kind=str(data.get("deliverable_kind", "custom")),
                tags=list(data.get("tags", [])),
                summary=str(data.get("summary", "")),
                contract_kind=str(data.get("contract_kind", "custom")),
                contract_required_dimensions=list(data.get("required_dimensions", [])),
                contract_acceptance_criteria=list(data.get("acceptance_criteria", [])),
            )
            markdown = generator.generate(doc)
            return {"status": "success", "markdown": markdown}
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    return router
