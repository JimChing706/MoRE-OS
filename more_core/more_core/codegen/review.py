"""多智能体代码评审面板 — L0 代码循环的 Self-Audit 角色（BPR C）。

对生成/修复后的代码产物运行一组并行的专职评审者（正确性/安全/质量），
每个评审者返回结构化裁决；仅当没有任何 P1/P2 缺陷时面板才 *approved*
（P3 可选改进带说明放行）。被否决的缺陷清单回灌 L0 修复循环作为失败输入，
对应 BPR 规范中"Self-Audit 无 P1/P2 缺陷；P3 允许带说明放行"。

设计原则:
- 评审者并行运行（asyncio.gather），单角色失败不阻断整场评审
- JSON 健壮解析：裸 JSON → 围栏/花括号提取，无法解析降级为 reject 占位
- 评审只读代码 + 任务描述，不依赖沙箱状态，可独立单测
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

_log = logging.getLogger(__name__)

# 评审系统提示：约束评审者输出，明确 P1/P2/P3 分级语义。
REVIEW_SYSTEM = (
    "你是 MoRE L0 代码生成流水线的多智能体代码评审面板成员。"
    "你只负责评审任务描述与给定代码，输出结构化 JSON 裁决。"
)

# 评审者角色与职责（并行独立评审）。
REVIEWER_ROLES: dict[str, str] = {
    "correctness": (
        "你是正确性评审者。检查: 1)算法与逻辑错误 2)边界条件与空输入 3)异常处理缺失 "
        "4)对任务描述的功能覆盖。只有逻辑正确、覆盖任务需求才 approve。"
    ),
    "security": (
        "你是安全评审者。检查: 1)危险操作(eval/exec/shell/子进程) 2)注入与不可信输入 "
        "3)资源泄漏与无限循环 4)权限与数据暴露。存在安全缺陷必须 reject。"
    ),
    "quality": (
        "你是质量评审者。检查: 1)可读性与命名 2)API 契约与调用方式 3)明显性能问题 "
        "4)测试与验证是否覆盖关键路径。仅有可读性/风格类问题属于 P3。"
    ),
}

# 评审裁决 JSON 约束。
REVIEW_SCHEMA = (
    "你的回答必须是一个 JSON 对象，只包含以下字段:\n"
    '- "verdict": "approve" 或 "reject"\n'
    '- "severity": "P1"(必须修复的严重缺陷) / "P2"(应修复的重要问题) / "P3"(可选改进)\n'
    '- "findings": 字符串数组，每个元素是一个具体缺陷描述\n'
    '- "suggestion": 一个具体可操作的修复建议\n'
    "严禁输出 JSON 以外的任何内容。"
)


@dataclass
class ReviewerFinding:
    """一条评审发现。"""

    role: str
    severity: str  # P1 | P2 | P3
    message: str
    suggestion: str = ""


@dataclass
class CodeReviewResult:
    """评审面板交付物。"""

    approved: bool  # 无 P1/P2 缺陷
    findings: list[ReviewerFinding] = field(default_factory=list)
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """一行摘要：通过或列出 P1/P2 缺陷。"""
        if self.approved:
            return "code review approved (no P1/P2 findings)"
        parts = []
        for f in self.findings:
            if f.severity in ("P1", "P2"):
                parts.append(f"[{f.role}:{f.severity}] {f.message}")
        return "; ".join(parts)

    def as_error(self) -> str:
        """转为合成沙箱失败信息，供修复循环消费。"""
        return f"code review rejected: {self.summary}"


def build_review_prompt(query: str, code: str, role: str, instruction: str) -> str:
    """构造单个评审者的提示词。"""
    return "\n\n".join(
        [
            f"=== 评审者: {role} ===",
            instruction,
            f"=== 任务描述 ===\n{query[:4000]}",
            f"=== 待评审代码 ===\n```python\n{code}\n```",
            REVIEW_SCHEMA,
        ]
    ).strip()


def parse_review(raw: str, role: str) -> dict[str, Any]:
    """健壮解析单个评审者的 JSON 裁决。

    支持裸 JSON 与夹杂在文本中的 JSON；解析失败降级为 reject 占位，
    保证聚合器永远拿到结构化的 verdict/severity/findings。
    """
    text = str(raw or "").strip()
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        _log.warning("无法解析评审者 '%s' 输出为 JSON: %s", role, text[:200])
        return {
            "role": role,
            "verdict": "reject",
            "severity": "P2",
            "findings": ["评审者输出无法解析"],
            "suggestion": "",
        }
    parsed.setdefault("role", role)
    parsed.setdefault("findings", [])
    parsed.setdefault("suggestion", "")
    verdict = parsed.get("verdict")
    if verdict not in ("approve", "reject"):
        parsed["verdict"] = "reject"
    severity = parsed.get("severity")
    if severity not in ("P1", "P2", "P3"):
        parsed["severity"] = "P2"
    return parsed


async def run_code_review(
    complete: Callable[[str], Awaitable[Any]],
    query: str,
    code: str,
    *,
    roles: list[str] | None = None,
) -> tuple[CodeReviewResult, int, int]:
    """并行运行评审者面板，聚合裁决。

    Args:
        complete: ``await complete(prompt) -> resp``，resp 需有 ``content`` 属性
            （可选 ``prompt_tokens`` / ``completion_tokens`` 用于记账）。
        query: 任务描述。
        code: 待评审的代码产物（已提取、已过安全检查）。
        roles: 评审者角色名；默认全部 ``REVIEWER_ROLES``。

    Returns:
        ``(CodeReviewResult, input_tokens, output_tokens)``。
    """
    role_names = roles or list(REVIEWER_ROLES)
    total_in, total_out = 0, 0

    async def _one(role: str) -> dict[str, Any]:
        nonlocal total_in, total_out
        prompt = build_review_prompt(query, code, role, REVIEWER_ROLES[role])
        resp = await complete(prompt)
        total_in += int(getattr(resp, "prompt_tokens", 0) or 0)
        total_out += int(getattr(resp, "completion_tokens", 0) or 0)
        return parse_review(getattr(resp, "content", ""), role)

    raw = await asyncio.gather(*[_one(r) for r in role_names], return_exceptions=True)

    verdicts: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, out in enumerate(raw):
        if not isinstance(out, dict):
            errors.append(f"[{role_names[i]}] 评审失败: {out}")
            _log.warning("评审者 '%s' 失败: %s", role_names[i], out)
        else:
            verdicts.append(out)

    findings: list[ReviewerFinding] = []
    for v in verdicts:
        for msg in v.get("findings", []):
            if not isinstance(msg, str) or not msg.strip():
                continue
            findings.append(
                ReviewerFinding(
                    role=str(v.get("role", "?")),
                    severity=str(v.get("severity", "P2")),
                    message=msg.strip(),
                    suggestion=str(v.get("suggestion", "")),
                )
            )

    # A panel with zero verdicts (every reviewer errored) must not approve —
    # fail closed rather than silently pass code that was never reviewed.
    approved = bool(verdicts) and not any(f.severity in ("P1", "P2") for f in findings)
    return (
        CodeReviewResult(approved=approved, findings=findings, verdicts=verdicts, errors=errors),
        total_in,
        total_out,
    )
