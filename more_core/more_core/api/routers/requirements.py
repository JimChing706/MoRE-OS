"""Requirements router — parse, import, validate, export."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from ...runtime.orchestrator import MoRECore
from ...requirements import requirements_to_tasks, parse_requirements
from ...core.types import TaskRequest, TaskType
from .tasks import _task_store


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.post("/requirements/parse", dependencies=[Depends(require_api_key)])
    async def parse_requirements_doc(content: dict[str, str]) -> dict[str, Any]:
        markdown = content.get("content", "")
        if not markdown:
            return {"error": "No content provided", "status": "failed"}
        try:
            doc = parse_requirements(markdown)
            return {
                "status": "success",
                "document": {
                    "title": doc.title,
                    "description": doc.description,
                    "version": doc.version,
                    "author": doc.author,
                    "created_at": doc.created_at,
                    "item_count": len(doc.items),
                },
                "items": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "description": item.description[:200] + "..."
                        if len(item.description) > 200
                        else item.description,
                        "priority": item.priority,
                        "type": item.type,
                        "acceptance_criteria": item.acceptance_criteria[:3],
                        "estimated_hours": item.estimated_hours,
                    }
                    for item in doc.items
                ],
            }
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    @router.post("/requirements/import", dependencies=[Depends(require_api_key)])
    async def import_requirements(content: dict[str, str]) -> dict[str, Any]:
        markdown = content.get("content", "")
        auto_start_val = content.get("auto_start", False)
        auto_start = (
            str(auto_start_val).lower() == "true"
            if isinstance(auto_start_val, str)
            else bool(auto_start_val)
        )
        if not markdown:
            return {"error": "No content provided", "status": "failed"}
        try:
            tasks = requirements_to_tasks(markdown)
            results = []
            for task in tasks:
                task_id = task["id"]
                _task_store.create_task(
                    task_id,
                    {
                        "task_id": task_id,
                        "title": task["title"],
                        "description": task.get("description", ""),
                        "context": task.get("context", {}),
                        "status": "pending",
                        "progress": 0,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            if auto_start:
                for task in tasks:
                    task_id = task["id"]
                    _task_store.update_task(
                        task_id,
                        {
                            "status": "in_progress",
                            "started_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    req = TaskRequest(
                        type=TaskType.NLP_TASK,
                        query=task["description"] or task["title"],
                        context=task.get("context", {}),
                    )
                    result = await core.execute(req)
                    results.append(
                        {
                            "task_id": task_id,
                            "title": task["title"],
                            "status": "completed",
                            "result": result.output,
                            "progress": 100,
                        }
                    )
                    _task_store.update_task(
                        task_id,
                        {
                            "status": "completed",
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "result": result.output,
                            "progress": 100,
                        },
                    )
            else:
                results = [
                    {
                        "task_id": t["id"],
                        "title": t["title"],
                        "description": t.get("description", ""),
                        "status": "pending",
                        "progress": 0,
                    }
                    for t in tasks
                ]
            return {
                "status": "success",
                "document_title": parse_requirements(markdown).title,
                "total_requirements": len(tasks),
                "tasks": results,
            }
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    @router.get("/requirements/templates")
    async def get_requirement_templates() -> dict[str, Any]:
        return {
            "templates": [
                {
                    "id": "basic",
                    "name": "Basic Feature",
                    "description": "Simple feature requirement template",
                    "template": "# 新功能需求\n\n**版本**: 1.0.0\n**作者**: [Your Name]\n\n## 需求描述\n\n[Describe the feature here]\n\n## 功能点\n\n- [ ] 功能点1: [Description]\n- [ ] 功能点2: [Description]\n\n### 验收标准\n\n- 验收标准1\n- 验收标准2\n\n**优先级**: 高\n**预计时间**: 8小时\n",
                },
                {
                    "id": "detailed",
                    "name": "Detailed Specification",
                    "description": "Comprehensive requirement template with full details",
                    "template": "# 详细需求规格\n\n**项目**: [Project Name]\n**版本**: 1.0.0\n**作者**: [Author]\n**日期**: 2024-01-01\n\n## 概述\n\n[Project overview and goals]\n\n## 功能需求\n\n### FR-001: [Feature Name]\n\n**描述**: [Detailed description]\n\n**优先级**: 高\n\n**验收标准**:\n- 标准1\n- 标准2\n\n**预计时间**: 8小时\n\n### FR-002: [Feature Name 2]\n\n**描述**: [Description]\n\n**优先级**: 中\n\n**验收标准**:\n- 标准1\n",
                },
            ]
        }

    @router.post("/requirements/validate")
    async def validate_requirements(content: dict[str, str]) -> dict[str, Any]:
        markdown = content.get("content", "")
        if not markdown:
            return {"error": "No content provided", "status": "failed"}
        try:
            doc = parse_requirements(markdown)
            issues = []
            if not doc.title:
                issues.append({"type": "warning", "field": "title", "message": "文档缺少标题"})
            if len(doc.items) == 0:
                issues.append({"type": "error", "field": "items", "message": "文档缺少功能点"})
            for i, item in enumerate(doc.items):
                if not item.title:
                    issues.append(
                        {
                            "type": "error",
                            "field": f"item_{i}",
                            "message": f"功能点 {i + 1} 缺少标题",
                        }
                    )
                if not item.description and len(item.acceptance_criteria) == 0:
                    issues.append(
                        {
                            "type": "warning",
                            "field": f"item_{i}",
                            "message": f"功能点 {item.id} 缺少描述和验收标准",
                        }
                    )
                if item.estimated_hours == 0:
                    issues.append(
                        {
                            "type": "info",
                            "field": f"item_{i}",
                            "message": f"功能点 {item.id} 未设置预计时间",
                        }
                    )
            return {
                "status": "success",
                "valid": len([i for i in issues if i["type"] == "error"]) == 0,
                "issues": issues,
                "summary": {
                    "total_items": len(doc.items),
                    "total_issues": len(issues),
                    "errors": len([i for i in issues if i["type"] == "error"]),
                    "warnings": len([i for i in issues if i["type"] == "warning"]),
                    "info": len([i for i in issues if i["type"] == "info"]),
                },
            }
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    @router.get("/requirements/export/{doc_id}")
    async def export_requirements(doc_id: str, format: str = "markdown") -> dict[str, Any]:
        try:
            doc = parse_requirements(f"# Document {doc_id}\n\n(No content)")
            if format == "json":
                return {
                    "status": "success",
                    "format": "json",
                    "data": {
                        "title": doc.title,
                        "version": doc.version,
                        "author": doc.author,
                        "items": [
                            {
                                "id": item.id,
                                "title": item.title,
                                "description": item.description,
                                "priority": item.priority,
                                "type": item.type,
                                "estimated_hours": item.estimated_hours,
                                "acceptance_criteria": item.acceptance_criteria,
                            }
                            for item in doc.items
                        ],
                    },
                }
            elif format == "csv":
                csv_lines = ["ID,标题,优先级,类型,预计时间"]
                for item in doc.items:
                    csv_lines.append(
                        f'{item.id},"{item.title}",{item.priority},{item.type},{item.estimated_hours}'
                    )
                return {"status": "success", "format": "csv", "data": "\n".join(csv_lines)}
            else:
                return {"error": "Unsupported format", "status": "failed"}
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    return router
