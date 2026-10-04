"""Import Task Document router — parse, validate, import, generate, templates.

Follows the same pattern as requirements.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from ...core.import_task import (
    ImportTaskDocument,
    ImportTaskGenerator,
    ImportTaskParser,
    QualityGate,
    RequirementItem,
    ImportKillCriterion,
    ResourceBudget,
)
from ...runtime.orchestrator import MoRECore
from .tasks import _task_store, _execute_task_background_v2


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

    parser = ImportTaskParser()
    generator = ImportTaskGenerator()

    @router.post("/tasks/itd/parse", dependencies=[Depends(require_api_key)])
    async def parse_itd(content: dict[str, str]) -> dict[str, Any]:
        markdown = content.get("content", "")
        if not markdown:
            return {"error": "No content provided", "status": "failed"}
        try:
            doc = parser.parse(markdown)
            raw_warnings = doc._raw_frontmatter.get("_warnings", [])
            issues: list[dict[str, Any]] = []
            for i, w in enumerate(raw_warnings):
                issue_type = "warning"
                suggestion = ""
                if "模式A/B" in w or "模式C" in w:
                    suggestion = "建议使用标准模式A格式，包含完整的YAML frontmatter"
                elif "R006" in w:
                    suggestion = "请在tags数组中添加至少一个标签，如 [code, backend]"
                elif "R007" in w:
                    suggestion = "请在Executive Summary部分填写任务目标概述"
                elif "R009" in w:
                    suggestion = "请在Deliverable Contract中定义至少一条验收标准"
                elif "R012" in w:
                    suggestion = "请在Requirements部分添加至少一条REQ-xxx需求"
                elif "R013" in w:
                    suggestion = "请在frontmatter中添加created字段，格式ISO 8601: 2026-01-01T00:00:00Z"
                elif "R014" in w:
                    suggestion = "请在frontmatter中添加author字段标识任务负责人"
                issues.append(
                    {
                        "type": issue_type,
                        "message": str(w),
                        "line": 1 + i,
                        "col": 1,
                        "suggestion": suggestion,
                    }
                )
            return {
                "status": "success",
                "document": doc.to_dict(),
                "warnings": raw_warnings,
                "issues": issues,
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
            raw_warnings: list[str] = doc._raw_frontmatter.get("_warnings", [])
            issues: list[dict[str, Any]] = []
            for i, w in enumerate(raw_warnings):
                issue_type = "warning"
                suggestion = ""
                if "模式A/B" in w or "模式C" in w:
                    suggestion = "建议使用标准模式A格式，包含完整的YAML frontmatter"
                elif "R006" in w:
                    suggestion = "请在tags数组中添加至少一个标签，如 [code, backend]"
                elif "R007" in w:
                    suggestion = "请在Executive Summary部分填写任务目标概述"
                elif "R009" in w:
                    suggestion = "请在Deliverable Contract中定义至少一条验收标准"
                elif "R012" in w:
                    suggestion = "请在Requirements部分添加至少一条REQ-xxx需求"
                elif "R013" in w:
                    suggestion = "请在frontmatter中添加created字段，格式ISO 8601: 2026-01-01T00:00:00Z"
                elif "R014" in w:
                    suggestion = "请在frontmatter中添加author字段标识任务负责人"
                issues.append(
                    {
                        "type": issue_type,
                        "message": str(w),
                        "line": 1 + i,
                        "col": 1,
                        "suggestion": suggestion,
                    }
                )
            requirements_list = [r.to_dict() for r in doc.requirements]
            kill_criteria_list = [k.to_dict() for k in doc.kill_criteria]
            acceptance_criteria_list = list(doc.contract_acceptance_criteria)
            return {
                "status": "success",
                "valid": True,
                "issues": issues,
                "summary": {
                    "total_warnings": len(raw_warnings),
                    "total_requirements": len(doc.requirements),
                    "total_kill_criteria": len(doc.kill_criteria),
                    "total_acceptance_criteria": len(doc.contract_acceptance_criteria),
                    "requirements": requirements_list,
                    "kill_criteria": kill_criteria_list,
                    "acceptance_criteria": acceptance_criteria_list,
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

            parent_task_id = req.id
            now_iso = datetime.now(timezone.utc).isoformat()

            from ...core.guardrails.provenance_audit import get_default_layer as _get_prov_layer
            _prov = _get_prov_layer()

            blocking_level_from_fm = doc._raw_frontmatter.get("validation_blocking_level", "hard_block")

            _task_store.create_task(
                parent_task_id,
                {
                    "task_id": parent_task_id,
                    "title": doc.title,
                    "type": doc.type,
                    "priority": doc.priority,
                    "description": doc.summary[:500],
                    "requirement_count": len(doc.requirements),
                    "status": "in_progress" if auto_start else "pending",
                    "progress": 0,
                    "created_at": now_iso,
                    "context": {"parent_id": None, "is_parent": True, "requirements_count": len(doc.requirements),
                                "itd_content": markdown, "validation_blocking_level": blocking_level_from_fm},
                },
            )
            _prov.enroll(parent_task_id, "pending")
            _prov.mark(
                parent_task_id,
                "pending",
                payload={
                    "origin": "http_post_tasks_itd_import",
                    "requirements_count": len(doc.requirements),
                    "auto_start": bool(auto_start),
                    "title": doc.title,
                },
            )

            subtask_ids: list[str] = []
            for req_item in doc.requirements:
                subtask_id = f"{parent_task_id}-{req_item.id}"
                subtask_title = f"{req_item.id}: {req_item.title}"
                subtask_description = req_item.description or req_item.title
                _task_store.create_task(
                    subtask_id,
                    {
                        "task_id": subtask_id,
                        "title": subtask_title,
                        "type": doc.type,
                        "priority": req_item.priority.value if hasattr(req_item.priority, "value") else str(req_item.priority),
                        "description": subtask_description[:500],
                        "requirement_id": req_item.id,
                        "parent_id": parent_task_id,
                        "status": "pending",
                        "progress": 0,
                        "created_at": now_iso,
                        "context": {
                            "parent_id": parent_task_id,
                            "requirement_id": req_item.id,
                            "acceptance_criteria": req_item.acceptance_criteria,
                            "itd_content": markdown,
                            "validation_blocking_level": blocking_level_from_fm,
                        },
                    },
                )
                _prov.enroll(subtask_id, "pending")
                _prov.mark(
                    subtask_id,
                    "pending",
                    payload={
                        "origin": "http_post_tasks_itd_import_subtask",
                        "parent_id": parent_task_id,
                        "requirement_id": req_item.id,
                    },
                )
                subtask_ids.append(subtask_id)

            result_data: dict[str, Any] = {
                "task_id": parent_task_id,
                "title": doc.title,
                "type": doc.type,
                "status": "pending" if not auto_start else "running",
                "subtask_count": len(subtask_ids),
                "subtask_ids": subtask_ids,
            }

            if auto_start:
                task_info = {
                    "task_id": parent_task_id,
                    "title": doc.title,
                    "description": doc.summary[:500],
                    "type": doc.type,
                    "priority": doc.priority,
                    "context": {"parent_id": None, "requirements_count": len(doc.requirements),
                                "itd_content": markdown, "validation_blocking_level": blocking_level_from_fm},
                }
                asyncio.create_task(_execute_task_background_v2(parent_task_id, task_info, core))

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

    def _build_doc_from_dict(data: dict[str, Any]) -> ImportTaskDocument:
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
        pipeline = metadata.get("pipeline", {}) if isinstance(metadata.get("pipeline"), dict) else {}
        contract = data.get("deliverable_contract", {}) if isinstance(data.get("deliverable_contract"), dict) else {}
        context = data.get("context", {}) if isinstance(data.get("context"), dict) else {}
        budget_dict = data.get("resource_budget", {}) if isinstance(data.get("resource_budget"), dict) else {}

        requirements_raw = data.get("requirements", []) or []
        requirements_parsed: list[RequirementItem] = []
        for r in requirements_raw:
            if not isinstance(r, dict):
                continue
            req_priority_raw = r.get("priority", "medium")
            try:
                from ...core.import_task import Priority as _P
                req_priority = _P(req_priority_raw) if req_priority_raw in _P._value2member_map_ else _P.MEDIUM
            except Exception:
                from ...core.import_task import Priority as _P
                req_priority = _P.MEDIUM
            requirements_parsed.append(
                RequirementItem(
                    id=str(r.get("id", "")),
                    title=str(r.get("title", "")),
                    description=str(r.get("description", "")),
                    priority=req_priority,
                    acceptance_criteria=list(r.get("acceptance_criteria", []) or []),
                )
            )

        kc_raw = data.get("kill_criteria", []) or []
        kill_criteria_parsed: list[ImportKillCriterion] = []
        for k in kc_raw:
            if not isinstance(k, dict):
                continue
            kill_criteria_parsed.append(
                ImportKillCriterion(
                    id=str(k.get("id", "")),
                    condition=str(k.get("condition", "")),
                    severity=str(k.get("severity", "warning")),
                    timeline=str(k.get("timeline", "end-of-run")),
                    fallback=str(k.get("fallback", "")),
                )
            )

        qg_raw = contract.get("quality_gates", []) or []
        qg_parsed: list[QualityGate] = []
        for g in qg_raw:
            if not isinstance(g, dict):
                continue
            qg_parsed.append(
                QualityGate(
                    name=str(g.get("name", "")),
                    threshold=str(g.get("threshold", "")),
                )
            )

        doc = ImportTaskDocument(
            title=str(metadata.get("title", data.get("title", "Untitled"))),
            version=str(metadata.get("version", data.get("version", "1.0.0"))),
            author=str(metadata.get("author", data.get("author", ""))),
            created=str(
                metadata.get(
                    "created",
                    data.get("created", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                )
            ),
            type=str(metadata.get("type", data.get("type", "nlp_task"))),
            plugin_type=metadata.get("plugin_type", data.get("plugin_type")),
            priority=str(metadata.get("priority", data.get("priority", "medium"))),
            deliverable_kind=str(metadata.get("deliverable_kind", data.get("deliverable_kind", "custom"))),
            tags=list(metadata.get("tags", data.get("tags", [])) or []),
            estimated_hours=float(metadata.get("estimated_hours", data.get("estimated_hours", 0.0)) or 0.0),
            depends_on=list(metadata.get("depends_on", data.get("depends_on", [])) or []),
            pipeline_mode=pipeline.get("mode", metadata.get("pipeline_mode")),
            pipeline_prepend=list(pipeline.get("prepend", []) or []),
            pipeline_append=list(pipeline.get("append", []) or []),
            pipeline_skip=list(pipeline.get("skip", []) or []),
            target_confidence=float(metadata.get("target_confidence", 60.0) or 60.0),
            max_iterations=int(metadata.get("max_iterations", 10) or 10),
            timeout_s=float(metadata.get("timeout_s", 60.0) or 60.0),
            allow_self_improvement=bool(metadata.get("allow_self_improvement", False)),
            require_metacognitive=bool(metadata.get("require_metacognitive", False)),
            kill_on_diverge=bool(metadata.get("kill_on_diverge", True)),
            summary=str(data.get("summary", "")),
            requirements=requirements_parsed,
            contract_kind=str(contract.get("kind", data.get("contract_kind", "custom"))),
            contract_required_dimensions=list(contract.get("required_dimensions", data.get("required_dimensions", [])) or []),
            contract_quality_gates=qg_parsed,
            contract_acceptance_criteria=list(contract.get("acceptance_criteria", data.get("acceptance_criteria", [])) or []),
            contract_min_output_length=int(contract.get("min_output_length", 100) or 100),
            kill_criteria=kill_criteria_parsed,
            budget=ResourceBudget(
                estimated_tokens=int(budget_dict.get("estimated_tokens", 0) or 0),
                estimated_duration_min=int(budget_dict.get("estimated_duration_min", 0) or 0),
                max_iterations=int(budget_dict.get("max_iterations", 10) or 10),
                per_provider=dict(budget_dict.get("per_provider", {}) or {}),
            ),
            context_background=str(context.get("background", "")),
            context_constraints=list(context.get("constraints", []) or []),
            context_references=list(context.get("references", []) or []),
            related_documents=list(data.get("related_documents", []) or []),
        )
        return doc

    @router.post("/tasks/itd/generate", dependencies=[Depends(require_api_key)])
    async def generate_itd(data: dict[str, Any]) -> dict[str, Any]:
        try:
            if "document" in data and isinstance(data["document"], dict):
                doc = _build_doc_from_dict(data["document"])
            else:
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
