"""L0 — Execution Layer.

Real execution: LLM generation → structured tool-call parsing → tool
dispatch via :class:`ToolRegistry` → optional iterative refinement.

The layer supports two execution modes:
1. **Direct LLM** — generate a textual answer (default).
2. **Tool-augmented** — when the LLM output contains ``<tool_call>`` blocks,
   parse them, invoke via ``core.tools``, feed results back for synthesis.

Code execution tasks are auto-routed to the ``python_exec`` builtin tool.
"""

from __future__ import annotations

import json
import re

from ..core.types import LayerId, TaskType
from ..core.unicode_utils import detect_language
from ..llm.provider import LLMRequest
from .base import Layer, LayerContext, LayerResult

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)

_MAX_TOOL_ROUNDS = 5

_SYSTEM_PROMPTS = {
    "zh": (
        "你是 MoRE L0 执行层。请针对用户任务给出最终、精确的回答。"
        "如需代码，请输出可直接运行的代码。请用中文回答。"
    ),
    "ja": (
        "あなたは MoRE L0 実行レイヤーです。ユーザーのタスクに対して最終的かつ正確な"
        "回答を生成してください。コードが必要な場合は実行可能なコードを出力してください。"
        "日本語で回答してください。"
    ),
    "ko": (
        "당신은 MoRE L0 실행 레이어입니다. 사용자의 작업에 대해 최종적이고 정확한 "
        "답변을 생성하세요. 코드가 필요한 경우 실행 가능한 코드를 출력하세요. "
        "한국어로 답변하세요."
    ),
    "en": (
        "You are the MoRE L0 execution layer. Produce the final, precise "
        "answer to the user's task. If code is required, output runnable code."
    ),
}


class ExecutionLayer(Layer):
    layer_id = LayerId.L0

    async def process(self, ctx: LayerContext) -> LayerResult:
        req = ctx.request
        tools_json = ctx.core.tools.list_schemas() if ctx.core.tools.list() else []
        tool_hint = ""
        if tools_json:
            tool_hint = (
                "\n\nYou have access to the following tools. "
                "To call a tool wrap the JSON in <tool_call>{...}</tool_call> tags.\n"
                + json.dumps(tools_json, indent=2, ensure_ascii=False)
            )

        system_prompt = ctx.scratch.get("system_prompt")
        if not system_prompt:
            lang = detect_language(req.query)
            system_prompt = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PROMPTS["en"]) + tool_hint

        # Build effective prompt: incorporate L4 subtask decomposition if present
        effective_prompt = req.query
        plan = ctx.scratch.get("plan")
        if plan and plan.get("decomposed") and len(plan.get("subtasks", [])) > 1:
            subtask_list = "\n".join(
                f"  {i+1}. {st}" for i, st in enumerate(plan["subtasks"])
            )
            effective_prompt = (
                f"{req.query}\n\n"
                f"[Task Plan — address each subtask in order]\n{subtask_list}"
            )
        
        # Use task-specific model routing
        provider = None
        model = None
        if hasattr(ctx.core, "task_model_router") and ctx.core.task_model_router:
            router = ctx.core.task_model_router
            provider = router.select_provider(req.type)
            model = router.select_model(req.type)
        
        llm_req = LLMRequest(
            prompt=effective_prompt,
            system=system_prompt,
            temperature=req.context.get("temperature", 0.7),
            max_tokens=req.context.get("max_tokens", 2048),
        )
        
        # Try primary model, with fallback chain if available
        if provider and hasattr(ctx.core, "task_model_router"):
            router = ctx.core.task_model_router
            chain = router.get_fallback_chain(req.type)
            from ..llm.manager import ProviderModelPair
            pairs = [
                ProviderModelPair(provider=p.provider, model=p.model)
                for p in chain
                if p.provider in ctx.core.llm.list_providers()
            ]
            if len(pairs) > 1:
                try:
                    resp = await ctx.core.llm.generate_with_fallback_chain(llm_req, pairs)
                except Exception:
                    resp = await ctx.core.llm.generate(llm_req, provider=provider, model_override=model)
            else:
                resp = await ctx.core.llm.generate(llm_req, provider=provider, model_override=model)
        else:
            resp = await ctx.core.llm.generate(llm_req, provider=provider, model_override=model)
        total_in = resp.prompt_tokens
        total_out = resp.completion_tokens
        output = resp.content

        # --- tool-call loop ---
        for _round in range(_MAX_TOOL_ROUNDS):
            calls = _TOOL_CALL_RE.findall(output)
            if not calls:
                break
            tool_outputs: list[str] = []
            for raw in calls:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    tool_outputs.append(f"[tool error] invalid JSON: {raw[:120]}")
                    continue
                name = payload.pop("tool", payload.pop("name", ""))
                result = await ctx.core.tools.invoke(name, payload)
                tool_outputs.append(
                    f"[{name}] success={result.success} output={result.output}"
                    + (f" error={result.error}" if result.error else "")
                )
            followup = LLMRequest(
                prompt=(
                    f"Original query: {req.query}\n\n"
                    f"Previous response:\n{output}\n\n"
                    "Tool results:\n" + "\n".join(tool_outputs)
                    + "\n\nSynthesise a final answer."
                ),
                system=system_prompt,
                temperature=0.4,
                max_tokens=2048,
            )
            resp2 = await ctx.core.llm.generate(followup)
            total_in += resp2.prompt_tokens
            total_out += resp2.completion_tokens
            output = resp2.content

        # --- auto code-exec for code tasks (post-generation safety check) ---
        if (
            req.type in (TaskType.CODE_GENERATION, TaskType.CODE_DEBUGGING)
            and ctx.core.tools.get("python_exec")
        ):
            code = self._extract_python(output)
            if code:
                # Run generated code through L3 rule engine before execution
                from ..ontology.rule_engine import Fact
                code_facts = [Fact(kind="code_output", data={"code": code})]
                l3_layer = ctx.core.get_layer(LayerId.L3)
                inference = l3_layer.rule_engine.run(code_facts) if hasattr(l3_layer, "rule_engine") else None
                if inference is None or not inference.violations:
                    sbx_result = await ctx.core.tools.invoke("python_exec", {"code": code})
                    ctx.scratch["sandbox_result"] = sbx_result
                else:
                    ctx.scratch["code_blocked"] = inference.violations

        return LayerResult(
            layer=self.layer_id,
            description="LLM generation + tool dispatch",
            output=output,
            confidence=0.85,
            input_tokens=total_in,
            output_tokens=total_out,
        )

    @staticmethod
    def _extract_python(text: str) -> str:
        """Best-effort extraction of a fenced python block."""
        lower = text.lower()
        for fence in ("```python", "```py"):
            idx = lower.find(fence)
            if idx != -1:
                start = idx + len(fence)
                end = text.find("```", start)
                if end > start:
                    return text[start:end].strip()
        return ""
