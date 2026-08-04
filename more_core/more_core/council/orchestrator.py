"""认知辩论编排器 v2 — 借鉴 ai_council 2 orchestrator 增强版。

v2 增强:
- 场景感知: 注入场景领域知识和关键词线索
- 模式感知: deep/standard/quick 影响思考深度
- 空值安全: 所有外部依赖均做 null/空检查
- 降级策略: 低置信度场景不阻断，降级继续
- 详细日志: 每个关键决策点落日志
- 分阶段错误隔离: 单角色失败不阻断整场辩论
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from ..core.errors import CouncilError

from .roles import InMemoryCharterProvider, RoleCharterProvider

_log = logging.getLogger(__name__)

# ── 场景领域知识映射（借鉴 ai_council 2 SCENE_DOMAIN_CONTEXT）─────────

SCENE_DOMAIN_CONTEXT: dict[str, str] = {
    "technical_validation": (
        "【领域提示】这是一个技术验证/数学建模类问题。"
        "请特别关注: 1)数学定义的精确性 2)验证方法的可操作性 3)工程实现与理论模型的差距 4)正确性的多层次定义"
    ),
    "software_engineering": (
        "【领域提示】这是一个软件工程/系统架构类问题。"
        "请特别关注: 1)架构质量(可维护性/可扩展性/耦合度) 2)工程实践(测试/CI/CD/监控) 3)技术债务 4)团队能力与资源约束"
    ),
    "code_architecture": (
        "【领域提示】这是一个架构设计类问题。"
        "请特别关注: 1)模块边界与耦合分析 2)演进路径和扩展点 3)技术选型的权衡 4)迁移成本和团队能力"
    ),
    "security_critical": (
        "【领域提示】这是一个安全关键类问题。"
        "请特别关注: 1)威胁建模(攻击者/攻击向量) 2)纵深防御 3)合规性要求 4)最小权限原则"
    ),
    "academic_research": (
        "【领域提示】这是一个学术研究/方法论类问题。"
        "请特别关注: 1)方法论的严谨性 2)可复现性 3)与现有工作的对比 4)创新性与实际贡献"
    ),
    "product_design": (
        "【领域提示】这是一个产品设计/用户体验类问题。"
        "请特别关注: 1)用户真实需求 vs 假设需求 2)使用场景与约束 3)竞品差异化 4)MVP验证路径"
    ),
    "strategy_decision": (
        "【领域提示】这是一个战略决策类问题。"
        "请特别关注: 1)资源分配效率 2)长期方向 vs 短期收益 3)风险评估与对冲 4)利益相关者影响"
    ),
}

# ── 模式指令（深度影响思考力度）─────────────────────────────────────

MODE_INSTRUCTIONS: dict[str, str] = {
    "deep": (
        "【深度模式】请进行深入的多维度分析:\n"
        "- 每个论点必须附带具体数据、案例或形式化推导\n"
        "- 必须考虑二阶效应和边界条件\n"
        "- 必须给出可操作的验证方法\n"
        "- 禁止使用模糊表述（除非明确标注为假设）"
    ),
    "standard": (
        "【标准模式】请进行平衡的分析:\n"
        "- 关键论点附带数据或案例支撑\n"
        "- 考虑主要风险和机会\n"
        "- 给出可行的建议"
    ),
    "quick": (
        "【快速模式】请给出简洁的核心判断:\n"
        "- 一句话核心结论\n"
        "- 最关键的 1-2 个论点\n"
        "- 最大的一个风险"
    ),
}

# ── 基础提示词模板 ──────────────────────────────────────────────────

SCHEMA_INSTRUCTION = (
    "你的回答必须是一个 JSON 对象，且只包含以下字段:\n"
    '- "role": 你的角色标识\n'
    '- "stage": 当前阶段("independent" 或 "cross_review")\n'
    '- "core_judgment": 一句话核心判断(必须有明确立场)\n'
    '- "key_arguments": 1-3 个关键论点，每个是 {"point": 论点, "reasoning": 推理链}\n'
    '- "top_concern": 一个最关键的风险或关注点(必须具体)\n'
    '- "constructive_suggestion": 一个具体的改进方向(必须可操作)\n'
    '- "confidence": 你对这个判断的置信度("high"/"medium"/"low")\n'
    "严禁输出 JSON 以外的任何内容。"
)

ISOLATION_CONSTRAINT = (
    "【独立分析约束】你现在处于独立思考阶段: 只基于用户问题进行推理，"
    "不要猜测或回应其他角色可能采取的角度。"
    "这是为了确保每个角色的独立视角不被群体思维影响。"
)

DIRECTED_RESPONSE_INSTRUCTION = (
    "【交叉审查要求】你必须从其他角色的分析中选择一个具体论点进行定向回应，"
    '在输出中包含 "directed_response" 字段: '
    '{"target_role": 目标角色, "target_point": 目标论点, '
    '"stance": "support"/"challenge"/"supplement", "content": 回应内容}。\n'
    "要求: 必须引用对方的具体论点; stance 必须明确; 回应内容必须包含论据。"
    "禁止泛泛而谈。"
)

SYNTHESIS_PROMPT = """你是认知综合者，负责综合多位专家的独立分析和交叉审查结果。

【核心原则】
1. 诚实呈现分歧: 如果角色间存在根本性分歧，必须在 consensus_level 中如实反映
2. 决策框架: 当共识为 divided 时，在 core_conclusion 中说明根本分歧点，给出分层建议
3. 少数派保护: 任何角色的独特视角都不能被完全忽略
4. 可操作性: 每个建议必须具体可执行

输出必须是严格 JSON 格式:
{
  "core_conclusion": "一句话综合结论",
  "consensus_level": "strong|moderate|weak|divided",
  "key_consensus": ["共识点1", ...],
  "key_disputes": [{"topic": "争议主题", "positions": {"role_a": "立场", "role_b": "立场"}}],
  "risk_assessment": [{"risk": "风险", "severity": "high|medium|low", "mitigation": "缓解建议"}],
  "action_items": [{"action": "行动", "priority": "immediate|short_term|medium_term"}],
  "information_gaps": ["需要补充的信息"],
  "overall_confidence": 0-100
}
禁止: 虚假一致、省略核心观点、制造不存在的分歧。"""


# ── 数据模型 ────────────────────────────────────────────────────────


@dataclass
class CouncilResult:
    """认知辩论的完整交付物。"""

    session_id: str
    question: str
    scene_label: str = "general"
    scene_confidence: float = 0.0
    mode: str = "standard"
    independent_outputs: list[dict[str, Any]] = field(default_factory=list)
    cross_review_outputs: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def core_conclusion(self) -> str:
        if self.synthesis:
            core = self.synthesis.get("core_conclusion", "")
            return core if isinstance(core, str) else str(core)
        return ""

    @property
    def consensus_level(self) -> str:
        if self.synthesis:
            level = self.synthesis.get("consensus_level", "unknown")
            return level if isinstance(level, str) else str(level)
        return "unknown"

    def summary(self) -> str:
        if self.synthesis:
            s = self.synthesis
            return (
                f"[council:{self.scene_label}] {s.get('consensus_level', '?')}共识 "
                f"(置信度{s.get('overall_confidence', 'N/A')}) "
                f"{s.get('core_conclusion', '')[:80]}"
            )
        return f"[council:{self.scene_label}] 未完成(错误: {len(self.errors)})"


# ── 内部辅助 ─────────────────────────────────────────────────────────


def _get_scene_context(
    scene_label: str,
    matched_keywords: list[str] | None = None,
) -> str:
    """生成场景上下文提示（借鉴 ai_council 2 prompt_builder）。"""
    parts = []
    if scene_label in SCENE_DOMAIN_CONTEXT:
        parts.append(SCENE_DOMAIN_CONTEXT[scene_label])
    elif scene_label != "general":
        parts.append(f"【领域提示】当前场景: {scene_label}。请根据问题性质进行针对性分析。")

    if matched_keywords:
        parts.append(f"【关键词线索】问题涉及: {', '.join(matched_keywords[:8])}")

    return "\n".join(parts) if parts else ""


def _get_mode_instruction(mode: str) -> str:
    """生成模式指令。"""
    return MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["standard"])


# ── 编排器 ──────────────────────────────────────────────────────────


class CouncilOrchestrator:
    """认知辩论编排器 v2 — 场景感知 + 模式驱动。

    用法:
        orchestrator = CouncilOrchestrator(llm_complete_fn)
        result = await orchestrator.deliberate(
            "这个微服务拆分方案是否合理？",
            scene_label="code_architecture", mode="deep",
        )
    """

    DEFAULT_CORE_ROLES = ["analyst", "architect", "critic", "pragmatist", "innovator"]

    def __init__(
        self,
        complete_fn: Any,
        charter_provider: RoleCharterProvider | None = None,
        core_roles: list[str] | None = None,
    ):
        self._complete = complete_fn
        self._charters = charter_provider or InMemoryCharterProvider()
        self._core_roles = core_roles or list(self.DEFAULT_CORE_ROLES)

    async def deliberate(
        self,
        question: str,
        scene_label: str = "general",
        mode: str = "standard",
        matched_keywords: list[str] | None = None,
    ) -> CouncilResult:
        """执行完整的 3 阶段认知辩论。

        Args:
            question: 用户问题
            scene_label: 场景分类标签 (影响领域提示注入)
            mode: deep / standard / quick
            matched_keywords: 场景匹配的关键词
        """
        # ── 空值安全 ──
        question = str(question or "").strip()
        if not question:
            result = CouncilResult(
                session_id=uuid.uuid4().hex[:12],
                question="",
                scene_label=scene_label,
                mode=mode,
            )
            result.errors.append("用户问题为空，无法执行辩论")
            return result

        session_id = uuid.uuid4().hex[:12]
        result = CouncilResult(
            session_id=session_id,
            question=question,
            scene_label=scene_label,
            mode=mode,
        )

        _log.info(
            "辩论启动 session=%s scene=%s mode=%s roles=%s",
            session_id,
            scene_label,
            mode,
            self._core_roles,
        )

        try:
            # ── Stage 1: Independent ──────────────────────────────
            _log.debug("[%s] Stage 1: 独立分析开始", session_id)
            independent_tasks = []
            for role_id in self._core_roles:
                independent_tasks.append(
                    self._run_independent(
                        role_id,
                        question,
                        scene_label=scene_label,
                        mode=mode,
                        matched_keywords=matched_keywords,
                    )
                )
            raw_outputs = await asyncio.gather(*independent_tasks, return_exceptions=True)

            for i, out in enumerate(raw_outputs):
                if isinstance(out, Exception):
                    result.errors.append(f"[{self._core_roles[i]}] 独立分析失败: {out}")
                    _log.warning(
                        "[%s] 角色 '%s' 独立分析失败: %s", session_id, self._core_roles[i], out
                    )
                else:
                    result.independent_outputs.append(cast(dict[str, Any], out))

            if len(result.independent_outputs) < 2:
                result.errors.append("有效独立分析不足(需至少 2 个角色)，无法继续")
                _log.warning(
                    "[%s] 独立分析不足: %d 个有效输出", session_id, len(result.independent_outputs)
                )
                return result

            _log.info(
                "[%s] Stage 1 完成: %d 个角色输出", session_id, len(result.independent_outputs)
            )

            # ── Stage 2: Cross-Review ─────────────────────────────
            _log.debug("[%s] Stage 2: 交叉审查开始", session_id)
            cross_tasks = []
            for role_id in self._core_roles:
                cross_tasks.append(
                    self._run_cross_review(
                        role_id,
                        question,
                        result.independent_outputs,
                        scene_label=scene_label,
                        mode=mode,
                        matched_keywords=matched_keywords,
                    )
                )
            raw_reviews = await asyncio.gather(*cross_tasks, return_exceptions=True)

            for i, out in enumerate(raw_reviews):
                if isinstance(out, Exception):
                    result.errors.append(f"[{self._core_roles[i]}] 交叉审查失败: {out}")
                    _log.warning(
                        "[%s] 角色 '%s' 交叉审查失败: %s", session_id, self._core_roles[i], out
                    )
                else:
                    result.cross_review_outputs.append(cast(dict[str, Any], out))

            _log.info(
                "[%s] Stage 2 完成: %d 个审查输出", session_id, len(result.cross_review_outputs)
            )

            # ── Stage 3: Synthesis ─────────────────────────────────
            _log.debug("[%s] Stage 3: 综合裁决开始", session_id)
            try:
                synthesis = await self._run_synthesis(
                    question,
                    result.independent_outputs + result.cross_review_outputs,
                    scene_label=scene_label,
                    mode=mode,
                    matched_keywords=matched_keywords,
                )
                result.synthesis = synthesis
                _log.info(
                    "[%s] Stage 3 完成: consensus=%s",
                    session_id,
                    synthesis.get("consensus_level", "?"),
                )
            except Exception as e:
                result.errors.append(f"综合裁决失败: {e}")
                _log.warning("[%s] 综合裁决失败: %s", session_id, e)

        except Exception as e:
            result.errors.append(f"辩论流程异常: {e}")
            _log.error("[%s] 辩论流程异常: %s", session_id, e)

        return result

    # ── 内部方法 ───────────────────────────────────────────────────

    async def _run_independent(
        self,
        role_id: str,
        question: str,
        scene_label: str = "general",
        mode: str = "standard",
        matched_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """阶段 1: 角色独立分析（认知隔离 + 场景感知）。"""
        try:
            charter = self._charters.get(role_id)
        except KeyError as e:
            raise CouncilError(f"角色 '{role_id}' 章程不存在: {e}")

        charter = str(charter or "").strip() or f"你是角色 {role_id}"
        question = str(question or "").strip() or "(用户未提供问题)"

        scene_ctx = _get_scene_context(scene_label, matched_keywords)
        mode_instruction = _get_mode_instruction(mode)

        prompt = "\n\n".join(
            [
                f"=== 角色: {role_id} ===",
                charter,
                ISOLATION_CONSTRAINT,
                mode_instruction,
                scene_ctx if scene_ctx else "",
                f"=== 用户问题 ===\n{question}",
                SCHEMA_INSTRUCTION,
            ]
        ).strip()

        raw = await self._complete(prompt)
        return self._parse_output(raw, role_id, "independent")

    async def _run_cross_review(
        self,
        role_id: str,
        question: str,
        revealed_outputs: list[dict[str, Any]],
        scene_label: str = "general",
        mode: str = "standard",
        matched_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """阶段 2: 交叉审查（渐进揭示 + 场景感知）。"""
        try:
            charter = self._charters.get(role_id)
        except KeyError as e:
            raise CouncilError(f"角色 '{role_id}' 章程不存在: {e}")

        charter = str(charter or "").strip() or f"你是角色 {role_id}"
        question = str(question or "").strip() or "(用户未提供问题)"

        others = [
            {k: v for k, v in o.items() if k != "directed_response"}
            for o in revealed_outputs
            if o.get("role") != role_id
        ]
        if not others:
            others = revealed_outputs  # fallback

        revealed = json.dumps(others, ensure_ascii=False, indent=2)
        scene_ctx = _get_scene_context(scene_label, matched_keywords)
        mode_instruction = _get_mode_instruction(mode)

        prompt = "\n\n".join(
            [
                f"=== 角色: {role_id} ===",
                charter,
                f"=== 用户问题 ===\n{question}",
                f"=== 其他角色的独立分析（已揭示） ===\n{revealed}",
                DIRECTED_RESPONSE_INSTRUCTION,
                mode_instruction,
                scene_ctx if scene_ctx else "",
                SCHEMA_INSTRUCTION,
            ]
        ).strip()

        raw = await self._complete(prompt)
        return self._parse_output(raw, role_id, "cross_review")

    async def _run_synthesis(
        self,
        question: str,
        transcript: list[dict[str, Any]],
        scene_label: str = "general",
        mode: str = "standard",
        matched_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """阶段 3: 综合裁决（场景感知）。"""
        full = json.dumps(transcript, ensure_ascii=False, indent=2)
        scene_ctx = _get_scene_context(scene_label, matched_keywords)
        mode_instruction = _get_mode_instruction(mode)

        prompt = "\n\n".join(
            [
                SYNTHESIS_PROMPT,
                mode_instruction,
                scene_ctx if scene_ctx else "",
                f"=== 用户问题 ===\n{question.strip()}",
                f"=== 完整辩论记录 ===\n{full}",
            ]
        ).strip()

        raw = await self._complete(prompt)
        return self._parse_json(raw)

    @staticmethod
    def _parse_output(raw: str, role: str, stage: str) -> dict[str, Any]:
        """解析角色输出，注入 role/stage 元数据。"""
        parsed = CouncilOrchestrator._parse_json(raw)
        parsed.setdefault("role", role)
        parsed.setdefault("stage", stage)
        return parsed

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """从 LLM 响应中提取 JSON（健壮解析）。"""
        text = raw.strip()
        try:
            return cast(dict[str, Any], json.loads(text))
        except json.JSONDecodeError:
            pass
        import re

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return cast(dict[str, Any], json.loads(match.group()))
            except json.JSONDecodeError:
                pass
        _log.warning("无法解析 LLM 输出为 JSON: %s", text[:200])
        return {
            "role": "unknown",
            "stage": "unknown",
            "core_conclusion": text[:500],
            "consensus_level": "unknown",
            "key_consensus": [],
            "key_disputes": [],
            "risk_assessment": [],
            "action_items": [],
            "information_gaps": [],
            "overall_confidence": 0,
        }
