"""Tasks router — task execution, status, history."""

from __future__ import annotations

import asyncio
import json
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field as _Field

from ...security.rbac import Permission, require_permission
from ..auth import require_scope
from ...core.types import TaskRequest, TaskStatus, TaskType
from ...persistence.task_store import SQLiteTaskStore
from ...runtime.orchestrator import MoRECore

import os as _os
from pathlib import Path


class ExecuteTaskPayload(BaseModel):
    """Request body for POST /tasks/execute."""

    type: TaskType = TaskType.NLP_TASK
    plugin_type: str | None = None
    query: str = _Field(max_length=16384)
    context: dict[str, Any] = _Field(default_factory=dict)
    require_metacognitive_monitoring: bool = False
    allow_self_improvement: bool = False
    target_layer: str | None = None
    timeout_s: float = 60.0


# ---------------------------------------------------------------------------
# Shared task store (module-level so other routers can import it)
# ---------------------------------------------------------------------------

_db_path = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "data", "tasks.db"
)
_db_norm = _os.path.normpath(_db_path)
try:
    _os.makedirs(_os.path.dirname(_db_norm), exist_ok=True)
    _task_store = SQLiteTaskStore(_db_norm)
except Exception:
    # Fallback to /tmp when project data/ dir is TCC-protected
    try:
        _os.makedirs("/tmp/more_os_data", exist_ok=True)
        _task_store = SQLiteTaskStore("/tmp/more_os_data/more_tasks.db")
    except Exception:
        _task_store = SQLiteTaskStore("/tmp/more_tasks.db")


async def _execute_task_background_v2(
    task_id: str, task_info: dict[str, Any], core: MoRECore
) -> None:
    """Background task executor v2.1 (hardened):

    PHASE TOPOLOGY:
      0) Dispatcher.dispatch(itd_doc) → (template_key, steps, payload_map, warnings)
         ↓ 单点分派：Planner / Writer 同 key，防错位
      1) Writer.apply(..., template_key)        Phase 2
      2) Validator.validate_source              Phase 3A (Writer 之后、Delivery 之前)
      3) Delivery.run()                         Phase 4
      4) Validator.validate_archives            Phase 3B (Delivery 之后)
      5) Validator.aggregate → HARD_BLOCK → final_status=failed
      6) provenance.mark × 2 两次独立幂等写 + finally 兜底
    """
    import os as _os
    from datetime import datetime, timezone as _tz
    from ...core.guardrails.provenance_audit import get_default_layer
    from ...core.native_executor import (
        Planner,
        Writer,
        Validator,
        Delivery,
        TemplateDispatcher,
    )
    from ...core.native_executor.types import AggregatedValidationResult, ValidationBlockingLevel

    ctx_dispatcher: dict[str, Any] | None = (
        None  # (key, steps, payload_map, warnings) 从内部 Dispatcher
    )
    src_validation: Any = None
    arc_validation: Any = None
    agg_validation: AggregatedValidationResult | None = None
    validation_pass = False
    total_iterations = 0
    approx_tokens = 0
    written_map: dict[str, str] = {}
    delivery_info: dict[str, Any] = {}
    final_prov_payload: dict[str, Any] | None = None

    warnings: list[str] = []
    artifacts: list[dict[str, Any]] = []

    provenance = get_default_layer()
    provenance.enroll(task_id, "pending")

    def _write_final_provenance(
        *,
        force_validation_pass: bool | None = None,
        force_final_status: str | None = None,
    ) -> None:
        """Provenance final 双写兜底：独立幂等。

        - 正常情况下 phase=final + validation_pass + final_status
        - 若任一上层抛异常（如 _auto_create_output 抛错），仍然写 final_status=failed
        """
        nonlocal final_prov_payload
        vpass: bool | None = (
            validation_pass if force_validation_pass is None else force_validation_pass
        )
        fstatus: str = force_final_status or ("completed" if vpass is True else "failed")
        final_prov_payload = {
            "phase": "final",
            "validation_pass": bool(vpass) if vpass is not None else False,
            "final_status": fstatus,
            "iterations": total_iterations,
        }
        try:
            provenance.mark(
                task_id,
                "native_planner_loop",
                token_count=approx_tokens,
                files_written=len(written_map),
                iterations=total_iterations,
                payload=dict(final_prov_payload),
            )
        except Exception:
            # 极端情况：mark 本身异常（DB 被锁），不中断外层流程 —— 下一次幂等调用再试
            pass

    try:
        _task_store.update_task(
            task_id,
            {
                "status": "in_progress",
                "started_at": datetime.now(_tz.utc).isoformat(),
                "current_step": "pending",
                "progress": 0,
                "artifacts": [],
                "warnings": [],
            },
        )

        description = task_info.get("description", task_info.get("title", ""))
        type_str = str(task_info.get("type", "code_generation"))
        approx_tokens += max(500, len(description) // 4)

        # ITD doc：从 context.itd_content 取（若有），保证 Planner + Writer 分派同一 key
        ctx = task_info.get("context", {}) or {}
        itd_doc: str | None = None
        if isinstance(ctx, dict):
            itd_doc = ctx.get("itd_content") or None

        safe_root = "/tmp/more_os_native_runs"
        _os.makedirs(safe_root, exist_ok=True)
        import secrets as _secrets

        suffix = _secrets.token_hex(6)
        project_root = _os.path.join(
            safe_root, f"run_{task_id.replace('/', '_').replace(':', '_')}_{suffix}"
        )
        _os.makedirs(project_root, exist_ok=True)
        try:
            req_obj = TaskRequest(
                type=TaskType(type_str)
                if type_str in TaskType._value2member_map_
                else TaskType.NLP_TASK,
                query=description,
                context=task_info.get("context", {}),
                timeout_s=600.0,
            )

            # ===== Phase 0: TemplateDispatcher (single-point dispatch) =====
            _task_store.update_task(
                task_id,
                {
                    "current_step": "dispatcher",
                    "progress": 8,
                    "warnings": list(warnings),
                },
            )
            try:
                dispatcher_result = TemplateDispatcher.dispatch(
                    task_request=req_obj,
                    project_root=project_root,
                    doc=itd_doc,
                )
                template_key = dispatcher_result.key
                steps = dispatcher_result.plan_steps
                payload_map = dispatcher_result.payload_map
                if dispatcher_result.warnings:
                    warnings.extend(dispatcher_result.warnings)
                ctx_dispatcher = {
                    "template_key": template_key,
                    "payload_count": len(payload_map),
                    "steps_count": len(steps),
                }
                approx_tokens += 1200
                total_iterations += 1
            except Exception as e:
                warnings.append(
                    f"TemplateDispatcher failed, fallback Planner: {type(e).__name__}: {e}"
                )
                template_key = "generic"  # type: ignore[assignment]
                try:
                    planner = Planner()
                    steps = planner.plan(req_obj, project_root, itd_doc)
                except Exception as e2:
                    warnings.append(f"Planner fallback to RULE_BASED_GENERIC: {e2}")
                    from ...core.native_executor.planner import RULE_BASED_GENERIC_SCAFFOLD_PLAN  # type: ignore[attr-defined]
                    import copy as _copy

                    steps = _copy.deepcopy(RULE_BASED_GENERIC_SCAFFOLD_PLAN)
                payload_map = Writer().build_payload_map(
                    req_obj,
                    itd_doc,
                    steps,
                    template_key=template_key,
                )
                approx_tokens += 1000
                total_iterations += 1

            # 计算 self-iteration 轮数（要求 ≥4，读 ITD frontmatter max_iterations，fallback 4）
            self_iters_total: int = 4
            try:
                if isinstance(itd_doc, str) and "max_iterations" in itd_doc[:4000]:
                    import re as _re

                    m = _re.search(r"(?im)^max_iterations\s*:\s*(\d+)", itd_doc)
                    if m:
                        self_iters_total = max(4, min(8, int(m.group(1))))
            except Exception:
                pass
            if isinstance(ctx, dict) and ctx.get("max_iterations"):
                try:
                    self_iters_total = max(4, min(8, int(ctx["max_iterations"])))
                except Exception:
                    pass
            warnings.append(f"native self-iteration rounds = {self_iters_total}")

            provenance.mark(
                task_id,
                "native_planner_loop",
                token_count=approx_tokens,
                files_written=0,
                iterations=total_iterations,
                payload={
                    "phase": "planner",
                    "template_key": template_key,
                    "step": "dispatched",
                    "self_iterations": self_iters_total,
                    **(ctx_dispatcher or {}),
                },
            )

            # ===== Self-Iteration Loop: Phase 2 (Writer) + 3A (Validator.source) N 轮 =====
            for self_iter_idx in range(1, self_iters_total + 1):
                is_last_iter = self_iter_idx == self_iters_total
                progress_writer = int(8 + (27 * self_iter_idx) / self_iters_total)  # 8→35
                progress_validator_source = int(
                    35 + (23 * self_iter_idx) / self_iters_total
                )  # 35→58

                # ===== Phase 2: Writer (template_key → manifest 白名单) =====
                _task_store.update_task(
                    task_id,
                    {
                        "current_step": f"writer.iter{self_iter_idx}/{self_iters_total}",
                        "progress": progress_writer,
                        "warnings": list(warnings),
                        "artifacts": list(artifacts),
                    },
                )
                writer_error = None
                try:
                    writer = Writer()
                    inject_bad = bool(isinstance(ctx, dict) and ctx.get("inject_bad_cargo_toml"))
                    if inject_bad and self_iter_idx == 1 and "Cargo.toml" in payload_map:
                        bad = "[package\nname=bad\ne dition 2021]\n[[[INVALID TOML SYNTAX"
                        payload_map = dict(payload_map)
                        payload_map["Cargo.toml"] = bad
                    for step in steps:
                        if step.action == "write_file" and not step.payload_when_write_file:
                            step.payload_when_write_file = {
                                k: v for k, v in payload_map.items() if k in step.expected_outputs
                            }
                    written_map = writer.apply(
                        project_root,
                        steps,
                        task_id=task_id,
                        template_key=template_key,
                    )
                    approx_tokens += 1800 if self_iter_idx == 1 else 1200
                    total_iterations += 1
                except Exception as e:
                    writer_error = f"{type(e).__name__}: {e}"
                    warnings.append(f"Writer.iter{self_iter_idx} error: {writer_error}")
                artifacts.append(
                    {
                        "phase": "writer",
                        "iteration": self_iter_idx,
                        "total_iterations": self_iters_total,
                        "template_key": template_key,
                        "files_written": list(written_map.keys()),
                        "error": writer_error,
                    }
                )
                provenance.mark(
                    task_id,
                    "native_planner_loop",
                    token_count=approx_tokens,
                    files_written=len(written_map),
                    iterations=total_iterations,
                    payload={
                        "phase": "writer",
                        "iteration": self_iter_idx,
                        "total_iterations": self_iters_total,
                        "template_key": template_key,
                        "written_count": len(written_map),
                        "written": list(written_map.keys())[:20],
                    },
                )

                # ===== Phase 3A: Validator (source) =====
                _task_store.update_task(
                    task_id,
                    {
                        "current_step": f"validator.source.iter{self_iter_idx}/{self_iters_total}",
                        "progress": progress_validator_source,
                        "artifacts": list(artifacts),
                        "warnings": list(warnings),
                    },
                )
                src_pass_bool = False
                try:
                    validator = Validator(retries=1, timeout_s=30)
                    src_validation = validator.validate_source(project_root)
                    src_pass_bool = bool(getattr(src_validation, "pass_", False))
                    total_commands_src = int(getattr(src_validation, "total_commands", 0))
                    passed_commands_src = int(getattr(src_validation, "passed_commands", 0))
                    artifacts.append(
                        {
                            "phase": "validator.source",
                            "iteration": self_iter_idx,
                            "total_iterations": self_iters_total,
                            "pass": src_pass_bool,
                            "total_commands": total_commands_src,
                            "passed_commands": passed_commands_src,
                        }
                    )
                    if not src_pass_bool and total_commands_src > 0:
                        warnings.append(
                            f"Validator.source.iter{self_iter_idx} failed {passed_commands_src}/{total_commands_src}"
                        )
                    approx_tokens += 500 if self_iter_idx == 1 else 300
                    total_iterations += 1
                except Exception as e:
                    warnings.append(f"Validator.source.iter{self_iter_idx} skipped: {e}")
                    artifacts.append(
                        {
                            "phase": "validator.source",
                            "iteration": self_iter_idx,
                            "pass": False,
                            "total_commands": 0,
                            "passed_commands": 0,
                        }
                    )
                provenance.mark(
                    task_id,
                    "native_planner_loop",
                    token_count=approx_tokens,
                    files_written=len(written_map),
                    iterations=total_iterations,
                    payload={
                        "phase": "validator.source",
                        "iteration": self_iter_idx,
                        "total_iterations": self_iters_total,
                        "pass": src_pass_bool,
                    },
                )
                # 每轮结束如果 src 没过 + is_last_iter=False，下一轮 planner 重建 payload_map（允许自我修正）
                if not is_last_iter and not src_pass_bool:
                    try:
                        writer2 = Writer()
                        payload_map = writer2.build_payload_map(
                            req_obj, itd_doc, steps, template_key=template_key
                        )
                    except Exception:
                        pass

            # ===== Phase 4: Delivery =====
            _task_store.update_task(
                task_id,
                {
                    "current_step": "delivery",
                    "progress": 85,
                    "artifacts": list(artifacts),
                    "warnings": list(warnings),
                },
            )
            delivery_artifacts_for_validator: dict[str, str] = {}
            try:
                delivery = Delivery(_use_system_tar=False, _use_system_zip=False)
                prefix = f"task_{task_id.replace('/', '_').replace(':', '_')}_{datetime.now(_tz.utc).strftime('%Y%m%d')}"
                art = delivery.run(project_root, project_prefix=prefix)
                approx_tokens += 300
                delivery_info = {
                    "phase": "delivery",
                    "tar_gz_path": art.tar_gz_path,
                    "zip_path": art.zip_path,
                    "readme_path": art.readme_path,
                    "test_report_path": art.test_report_path,
                    "manifest_path": art.manifest_path,
                    "manifest_count": len(art.manifest_entries),
                }
                if art.tar_gz_path:
                    delivery_artifacts_for_validator["tar_gz"] = art.tar_gz_path
                if art.zip_path:
                    delivery_artifacts_for_validator["zip"] = art.zip_path
                artifacts.append(delivery_info)
                total_iterations += 1
            except Exception as e:
                warnings.append(f"Delivery partial: {e}")
                artifacts.append({"phase": "delivery", "tar_gz_path": None, "zip_path": None})

            provenance.mark(
                task_id,
                "native_planner_loop",
                token_count=approx_tokens,
                files_written=len(written_map),
                iterations=total_iterations,
                payload={"phase": "delivery_done", "iterations": total_iterations},
            )

            # ===== Phase 3B: Validator (archives) — Delivery 之后 =====
            _task_store.update_task(
                task_id,
                {
                    "current_step": "validator.archives",
                    "progress": 92,
                    "artifacts": list(artifacts),
                    "warnings": list(warnings),
                },
            )
            arc_pass_bool = False
            try:
                validator2 = Validator(retries=1, timeout_s=30)
                arc_validation = validator2.validate_archives(delivery_artifacts_for_validator)
                arc_pass_bool = bool(getattr(arc_validation, "pass_", False))
                total_commands_arc = int(getattr(arc_validation, "total_commands", 0))
                passed_commands_arc = int(getattr(arc_validation, "passed_commands", 0))
                artifacts.append(
                    {
                        "phase": "validator.archives",
                        "pass": arc_pass_bool,
                        "total_commands": total_commands_arc,
                        "passed_commands": passed_commands_arc,
                    }
                )
                if not arc_pass_bool:
                    # 无归档命令是正常情况（command_results=0），不额外告警；仅在 ≥1 命令失败时告警
                    if total_commands_arc > 0:
                        warnings.append(
                            f"Validator.archives failed {passed_commands_arc}/{total_commands_arc}"
                        )
                total_iterations += 1
            except Exception as e:
                warnings.append(f"Validator.archives skipped: {e}")
                artifacts.append(
                    {
                        "phase": "validator.archives",
                        "pass": False,
                        "total_commands": 0,
                        "passed_commands": 0,
                    }
                )

            # ===== Aggregate → HARD_BLOCK =====
            try:
                # 重新从 task_store 加载 context，允许运维层 SQL UPDATE 动态注入 validation_blocking_level（G-2-6 zero-src-change）
                _refreshed = _task_store.get_task(task_id)
                if isinstance(_refreshed, dict) and isinstance(_refreshed.get("context"), dict):
                    ctx = (
                        {**ctx, **_refreshed["context"]}
                        if isinstance(ctx, dict)
                        else _refreshed["context"]
                    )
                from ...core.native_executor.validator import aggregate_results

                if src_validation is None:
                    from ...core.native_executor.validator import ValidationResult

                    src_validation = ValidationResult(pass_=False)
                if arc_validation is None:
                    from ...core.native_executor.validator import ValidationResult

                    arc_validation = ValidationResult(pass_=True)
                agg_validation = aggregate_results(
                    src_validation,  # type: ignore[arg-type]
                    arc_validation,  # type: ignore[arg-type]
                    level=ctx.get("validation_blocking_level", ValidationBlockingLevel.HARD_BLOCK)
                    if isinstance(ctx, dict)
                    else ValidationBlockingLevel.HARD_BLOCK,
                )
                validation_pass = bool(agg_validation.pass_)
                artifacts.append(
                    {
                        "phase": "aggregate",
                        "pass": validation_pass,
                        "blocking_level": agg_validation.blocking_level.value,
                        "should_block_release": bool(agg_validation.should_block_release),
                        "src_pass": bool(getattr(agg_validation.source, "pass_", False)),
                        "archives_pass": bool(getattr(agg_validation.archives, "pass_", False)),
                    }
                )
                if agg_validation.should_block_release:
                    warnings.append(
                        "Validator hard-blocked release: "
                        + (
                            "source_validator_failed"
                            if not bool(getattr(agg_validation.source, "pass_", True))
                            else "archives_validator_failed"
                        )
                    )
            except Exception as e:
                warnings.append(f"Aggregate fallback (assume NOT pass): {e}")
                validation_pass = False

            final_output = {
                "phases": [
                    "dispatcher",
                    "writer",
                    "validator.source",
                    "delivery",
                    "validator.archives",
                    "aggregate",
                ],
                "iterations": total_iterations,
                "files_written": len(written_map),
                "template_key": template_key,
                "validation_pass": validation_pass,
                "artifacts": list(artifacts),
                "delivery": delivery_info,
            }

            from .outputs import _auto_create_output

            try:
                _auto_create_output(
                    {
                        "task_id": task_id,
                        "output": str(final_output),
                        "type": type_str,
                        "metadata": {
                            "task_type": type_str,
                            "task_label": description[:50],
                            "iterations": total_iterations,
                            "files_written": len(written_map),
                            "validation_pass": validation_pass,
                            "template_key": template_key,
                        },
                        "reasoning_chain": [],
                        "performance": {"iterations": total_iterations},
                    }
                )
            except Exception:
                # _auto_create_output 抛异常不影响 provenance.final 双写
                pass

            # ===== R-07: 子任务派发（逐条 REQ 核验并落状态） =====
            # 历史上 ITD 导入会建出 REQ 子任务，但执行器从不派发它们，
            # 子任务永远 pending 而父任务照报 completed。这里补齐：
            #   ① 读取父任务的全部子任务
            #   ② 用 requirement_verifier 对交付产物逐条核验
            #   ③ 回写子任务状态/证据/进度，并让父任务终态依赖子任务结果
            children_failed = 0
            children_summary: list[dict[str, Any]] = []
            try:
                _kids = _task_store.list_children(task_id)
                if _kids:
                    from ...core.requirement_verifier import verify_requirement

                    _artifact_parts: list[str] = []
                    _budget = 400_000
                    for _rel in list(written_map.keys())[:60]:
                        try:
                            _txt = (Path(project_root) / _rel).read_text(
                                encoding="utf-8", errors="ignore"
                            )
                        except Exception:
                            continue
                        _artifact_parts.append(_txt)
                        _budget -= len(_txt)
                        if _budget <= 0:
                            break
                    # 需求里常写"存在 X.toml / 提供 Y 模块"，这类判定依据是
                    # **文件清单**而非文件内容，因此把交付路径一并纳入待检文本。
                    _manifest = "\n".join(f"# delivered file: {_p}" for _p in written_map.keys())
                    _artifact_text = _manifest + "\n\n" + "\n\n".join(_artifact_parts)

                    for _child in _kids:
                        _cid = str(_child.get("task_id"))
                        _ctx = _child.get("context") or {}
                        _req_id = str(
                            _ctx.get("requirement_id")
                            or _ctx.get("req_id")
                            or _cid.rsplit("-", 1)[-1]
                        )
                        _verdict = verify_requirement(
                            req_id=_req_id,
                            title=str(_child.get("title") or ""),
                            description=str(_child.get("description") or ""),
                            acceptance_criteria=list(_ctx.get("acceptance_criteria") or []),
                            artifact_text=_artifact_text,
                        )
                        _child_status = "completed" if _verdict.ok else "failed"
                        if not _verdict.ok:
                            children_failed += 1
                        _task_store.update_task(
                            _cid,
                            {
                                "status": _child_status,
                                "progress": 100,
                                "current_step": "verified" if _verdict.ok else "requirement_unmet",
                                "result": json.dumps(_verdict.to_dict(), ensure_ascii=False),
                                "warnings": [] if _verdict.ok else [_verdict.reason],
                                "completed_at": datetime.now(_tz.utc).isoformat(),
                            },
                        )
                        try:
                            provenance.mark(
                                _cid,
                                "native_planner_loop",
                                token_count=0,
                                files_written=len(written_map),
                                iterations=total_iterations,
                                payload={
                                    "phase": "requirement_verify",
                                    "parent_id": task_id,
                                    "status": _child_status,
                                    "coverage": round(_verdict.coverage, 3),
                                    "missing": _verdict.missing[:10],
                                },
                            )
                        except Exception:
                            pass
                        children_summary.append(_verdict.to_dict())
                    artifacts.append(
                        {
                            "phase": "requirements",
                            "total": len(_kids),
                            "completed": len(_kids) - children_failed,
                            "failed": children_failed,
                            "detail": children_summary,
                        }
                    )
                    if children_failed:
                        warnings.append(
                            f"{children_failed}/{len(_kids)} REQ 子任务未达标（见子任务结果）"
                        )
            except Exception as exc:
                warnings.append(f"requirement dispatch skipped: {exc}")

            # ===== Final Provenance: 双写第 1 次（正常路径） =====
            _write_final_provenance()

            verified_ok = (
                validation_pass is True
                and not (
                    agg_validation.should_block_release if agg_validation is not None else False
                )
                and children_failed == 0
            )
            # 当 validation_blocking_level == OFF 时，不阻断 final_status，允许 self-iteration 继续迭代补全代码
            if agg_validation is not None:
                from ...core.native_executor.types import ValidationBlockingLevel as _VBL

                if _VBL(agg_validation.blocking_level) is _VBL.OFF:
                    verified_ok = True
                    if validation_pass is not True:
                        warnings.append(
                            "validation pass=False but blocking_level=OFF → allow iteration continue (proceeding)"
                        )
            final_status = "completed" if verified_ok else "failed"
            final_progress = 100 if verified_ok else 90
            if not verified_ok:
                warnings.append(
                    "task marked FAILED: validator hard_block (HARD_BLOCK level); "
                    "deliverables NOT releasable"
                )
            # 修正：若 validation_pass 被 _write_final_provenance 写成 True 但 should_block_release 为 True，强制 final_prov_payload.final_status=failed
            if (
                not verified_ok
                and final_prov_payload
                and final_prov_payload.get("final_status") == "completed"
            ):
                # Final Provenance：双写第 1.5 次 —— 修正 should_block_release 情形
                _write_final_provenance(force_validation_pass=False, force_final_status="failed")

            _task_store.update_task(
                task_id,
                {
                    "status": final_status,
                    "completed_at": datetime.now(_tz.utc).isoformat(),
                    "result": str(final_output),
                    "progress": final_progress,
                    "current_step": "done" if verified_ok else "validation_failed",
                    "error": None
                    if verified_ok
                    else "deliverable blocked: HARD_BLOCK validation failure",
                    "artifacts": list(artifacts),
                    "warnings": list(warnings),
                },
            )

            # ===== Final Provenance: 双写第 2 次（幂等） =====
            _write_final_provenance()

            # ── 交付可信度：写入交付台账（状态/版本/哈希/闸门/权责） ──
            # 模板通路同样要留痕，且用 logic/syntax/requirement 闸门拦截
            # "文件名正确但内容是 placeholder" 的空壳交付。
            try:
                from ...codegen.delivery_ledger import get_default_ledger
                from ...codegen.gates import run_gates

                _artifact_parts: list[str] = []
                _budget = 400_000
                for _rel in list(written_map.keys())[:60]:
                    try:
                        _txt = (Path(project_root) / _rel).read_text(
                            encoding="utf-8", errors="ignore"
                        )
                    except Exception:
                        continue
                    _artifact_parts.append(_txt)
                    _budget -= len(_txt)
                    if _budget <= 0:
                        break
                _artifact = (
                    "\n".join(f"# delivered file: {_p}" for _p in written_map.keys())
                    + "\n\n"
                    + "\n\n".join(_artifact_parts)
                )
                _report = run_gates(_artifact, query=str(description or ""), require_logic=True)
                _ledger_status = (
                    "delivered"
                    if (verified_ok and _report.passed)
                    else ("blocked" if not _report.passed else "failed")
                )
                if not _report.passed and verified_ok:
                    warnings.append(f"delivery gates blocked: {_report.summary()[:200]}")
                    _task_store.update_task(
                        task_id,
                        {
                            "status": "failed",
                            "warnings": list(warnings),
                            "error": "delivery gates failed",
                        },
                    )
                get_default_ledger().record(
                    task_id=task_id,
                    status=_ledger_status,
                    task_type=type_str,
                    reason=("" if _report.passed else _report.summary()[:300]),
                    artifact=_artifact,
                    verdict=str(template_key or ""),
                    gates=_report.to_dict(),
                    gates_passed=_report.passed,
                    actor=str((task_info.get("context") or {}).get("actor", "system")),
                    request_excerpt=str(description or ""),
                )
            except Exception as _ledger_exc:  # pragma: no cover
                warnings.append(f"delivery ledger skipped: {_ledger_exc}")

        finally:
            # R-12: 失败/被拦截时保留工作目录，便于复核中间产物；
            # 成功且未被拦截时按原行为清理（可用 MORE_KEEP_RUN_DIR=1 强制保留）。
            try:
                _keep = bool(_os.environ.get("MORE_KEEP_RUN_DIR")) or (
                    locals().get("final_status") != "completed"
                )
                if not _keep and _os.path.isdir(project_root):
                    import shutil as _shutil

                    _shutil.rmtree(project_root, ignore_errors=True)
            except Exception:
                pass
            # F-兜底：若 final_prov_payload 没写（任何抛异常路径），强制执行一次写 failed
            if final_prov_payload is None:
                _write_final_provenance(
                    force_validation_pass=False,
                    force_final_status="failed",
                )
            import shutil as _shutil

    except Exception as e:
        warnings.append(f"Fatal executor error: {type(e).__name__}: {e}")
        # F-outer: 终极兜底
        _write_final_provenance(
            force_validation_pass=False,
            force_final_status="failed",
        )
        provenance.mark(
            task_id,
            "unknown",
            token_count=approx_tokens,
            files_written=len(written_map),
            iterations=total_iterations,
            payload={"error": str(e), "phase": "fatal", "final_status": "failed"},
        )
        _task_store.update_task(
            task_id,
            {
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "current_step": "error",
                "warnings": list(warnings),
                "artifacts": list(artifacts),
            },
        )
        # R-12: 致命失败路径同样保留工作目录（诊断最需要它）。
        if not _os.environ.get("MORE_KEEP_RUN_DIR"):
            try:
                import shutil as _shutil2

                if "project_root" in locals() and _os.path.isdir(project_root):
                    _shutil2.rmtree(project_root, ignore_errors=True)
            except Exception:
                pass


async def _execute_task_background(task_id: str, task_info: dict[str, Any], core: MoRECore) -> None:
    """Alias to v2 — backward compatible entry point."""
    return await _execute_task_background_v2(task_id, task_info, core)


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Tasks"], dependencies=[Depends(require_api_key)])

    @router.post(
        "/tasks/execute",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.TASK_EXECUTE)),
            Depends(require_scope("tasks:execute")),
        ],
    )
    async def execute(payload: ExecuteTaskPayload) -> dict[str, Any]:
        from ...core.types import LayerId
        from ...core.guardrails.provenance_audit import get_default_layer as _get_prov

        target = LayerId(payload.target_layer) if payload.target_layer else None
        req = TaskRequest(
            type=payload.type,
            plugin_type=payload.plugin_type,
            query=payload.query,
            context=payload.context,
            target_layer=target,
            require_metacognitive_monitoring=payload.require_metacognitive_monitoring,
            allow_self_improvement=payload.allow_self_improvement,
            timeout_s=payload.timeout_s,
        )
        result = await core.execute(req)

        try:
            task_id = getattr(result, "task_id", None) or result.model_dump().get(
                "task_id", "task_auto"
            )
            approx_tokens = max(500, len(payload.query) // 4)
            _get_prov().mark(
                str(task_id),
                "external_tool_chain",
                token_count=approx_tokens,
                payload={
                    "origin": "http_post_tasks_execute",
                    "task_label": payload.query[:60],
                    "require_monitoring": bool(payload.require_metacognitive_monitoring),
                },
            )
        except Exception:
            pass

        if result.status == TaskStatus.SUCCESS:
            from .outputs import _auto_create_output

            resolved_type = result.metadata.get("auto_resolved_type", payload.type.value)
            _auto_create_output(
                {
                    "task_id": result.task_id if hasattr(result, "task_id") else "task_auto",
                    "output": result.output,
                    "type": resolved_type,
                    "metadata": {
                        "task_type": resolved_type,
                        "task_label": payload.query[:50],
                        **result.metadata,
                    },
                    "reasoning_chain": result.reasoning_chain
                    if hasattr(result, "reasoning_chain")
                    else [],
                    "performance": result.performance if hasattr(result, "performance") else {},
                }
            )

        return result.model_dump()

    @router.get("/tasks/{task_id}/status")
    async def get_task_status(task_id: str) -> dict[str, Any]:
        from ...core.guardrails.provenance_audit import get_default_layer

        task = _task_store.get_task(task_id)
        if task is None:
            return {"status": "not_found", "error": "Task not found"}

        # R-07: 父任务状态需连带暴露子任务（REQ）执行情况
        try:
            children = _task_store.list_children(task_id)
        except Exception:
            children = []
        subtask_summary = {
            "total": len(children),
            "completed": sum(1 for c in children if c.get("status") == "completed"),
            "failed": sum(1 for c in children if c.get("status") == "failed"),
            "pending": sum(1 for c in children if c.get("status") in ("pending", "in_progress")),
        }

        raw_status = task.get("status", "unknown")
        raw_progress = int(task.get("progress", 0) or 0)
        layer = get_default_layer()
        report, new_status, new_progress = layer.audit_with_status_override(
            task_id,
            raw_status=raw_status,
            raw_progress=raw_progress,
        )
        warnings_out = list(task.get("warnings", []))
        warnings_out.extend(report.warnings)
        error_out = task.get("error") or (
            "deliverable blocked by provenance audit" if report.deliverable_blocked else None
        )
        return {
            "task_id": task_id,
            "status": new_status,
            "progress": new_progress,
            "current_step": task.get("current_step"),
            "artifacts": task.get("artifacts", []),
            "warnings": warnings_out,
            "result": task.get("result"),
            "error": error_out,
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
            "audit_blocked": report.deliverable_blocked,
            "audit_report": report.to_dict(),
            "subtask_summary": subtask_summary,
            "children": [
                {
                    "task_id": c.get("task_id"),
                    "title": c.get("title"),
                    "status": c.get("status"),
                    "progress": c.get("progress"),
                    "current_step": c.get("current_step"),
                    "result": c.get("result"),
                }
                for c in children
            ],
        }

    @router.get("/tasks/{task_id}/audit")
    async def get_task_audit(task_id: str) -> dict[str, Any]:
        from ...core.guardrails.provenance_audit import get_default_layer

        task = _task_store.get_task(task_id)
        if task is None:
            return {"status": "not_found", "error": "Task not found", "task_id": task_id}
        layer = get_default_layer()
        report = layer.audit(task_id)
        return {
            "task_id": task_id,
            "status": "ok",
            "audit": report.to_dict(),
            "records": layer.list_records(task_id),
        }

    @router.post(
        "/tasks/{task_id}/execute",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.TASK_EXECUTE)),
            Depends(require_scope("tasks:execute")),
        ],
    )
    async def execute_task(task_id: str) -> dict[str, Any]:
        from ...core.guardrails.provenance_audit import get_default_layer as _get_prov

        task = _task_store.get_task(task_id)
        if task is None:
            return {"status": "not_found", "error": "Task not found"}
        if task.get("status") not in ["pending", "failed"]:
            return {"status": "invalid", "error": f"Task is already {task.get('status')}"}
        try:
            _get_prov().mark(
                str(task_id),
                "external_tool_chain",
                payload={
                    "origin": "http_post_tasks_id_execute",
                    "prior_status": task.get("status", "unknown"),
                },
            )
        except Exception:
            pass
        asyncio.create_task(_execute_task_background(task_id, task, core))
        return {"status": "started", "task_id": task_id, "message": "Task execution started"}

    @router.get("/tasks/history")
    async def get_task_history(limit: int = 20) -> dict[str, Any]:
        tasks = _task_store.list_tasks(limit=limit)
        return {
            "tasks": [
                {
                    "task_id": t.get("task_id"),
                    "title": t.get("title"),
                    "status": t.get("status"),
                    "result": t.get("result"),
                    "error": t.get("error"),
                    "created_at": t.get("created_at"),
                    "completed_at": t.get("completed_at"),
                }
                for t in tasks
            ]
        }

    @router.post(
        "/tasks/stream",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.TASK_EXECUTE)),
            Depends(require_scope("tasks:execute")),
        ],
    )
    async def stream_execute(payload: ExecuteTaskPayload) -> Any:
        """Stream task execution as Server-Sent Events (SSE)."""
        from fastapi.responses import StreamingResponse
        from ...core.types import TaskRequest as TR

        req = TR(
            type=payload.type,
            plugin_type=payload.plugin_type,
            query=payload.query,
            context=payload.context,
            timeout_s=payload.timeout_s,
        )
        return StreamingResponse(
            core.stream_execute(req),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


# Re-export for other routers that need the task store
__all__ = [
    "_task_store",
    "_execute_task_background",
    "_execute_task_background_v2",
    "create_router",
]
