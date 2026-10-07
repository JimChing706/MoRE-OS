"""需求级验证器 — 把 ITD 的每条 REQ 变成可执行、可留痕的验收结论。

背景（RESIDUAL_RISKS R-07）：ITD 导入会为每条 REQ 建一个子任务，但执行器从不
派发它们 —— 子任务永远停在 ``pending``，父任务却报 ``completed``。

本模块提供**确定性**的逐条需求核验：从需求标题/描述/验收标准中抽取可校验的
关键符号，检查交付产物是否覆盖，产出 ``completed`` / ``failed`` + 覆盖率 +
证据。它不臆造业务语义，只回答"需求里点名的东西，产物里到底有没有"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["RequirementVerdict", "extract_checkpoints", "verify_requirement"]

# 太泛、不构成证据的词
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "use",
    "using",
    "code",
    "only",
    "output",
    "python",
    "rust",
    "typescript",
    "javascript",
    "make",
    "new",
    "all",
    "req",
    "requirement",
    "ac",
    "todo",
    "实现",
    "支持",
    "提供",
    "完成",
    "进行",
    "要求",
    "必须",
    "可以",
    "以及",
    "代码",
    "功能",
    "系统",
    "模块",
    "文件",
    "任务",
    "验收",
    "标准",
    "描述",
}

# 可校验符号：反引号名 / 函数类名 / 文件路径 / 带扩展名文件 / 大写缩写 / CJK 关键词
_BACKTICK = re.compile(r"`([^`]{2,40})`")
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
_PATHISH = re.compile(r"\b([A-Za-z0-9_./-]+\.(?:rs|ts|tsx|js|py|json|toml|md|yml|yaml|html|css))\b")
_CJK = re.compile(r"[\u4e00-\u9fff]{2,20}")
# 中文虚词/连接词：用于把长句切成较短的关键片段（"客户端只发送输入意图" → "客户端"/"发送输入意图"）
_CJK_BREAK = re.compile(r"[的了与和及或并只在到把被从对为是不必须支持实现进行提供完成要能会]")


def extract_checkpoints(*texts: str, limit: int = 12) -> list[str]:
    """从需求文本中抽取可校验的关键点（去重、保序）。

    中文部分会按虚词切成 2–8 字的片段，避免把整句当作一个必须逐字命中的 token
    （那会导致几乎所有需求都判 failed）。
    """
    corpus = "\n".join(t for t in texts if t)
    found: list[str] = []
    for pattern in (_BACKTICK, _PATHISH, _IDENT):
        for m in pattern.finditer(corpus):
            token = (m.group(1) if m.groups() else m.group(0)).strip()
            low = token.lower()
            if len(token) < 2 or low in _STOP or token.isdigit():
                continue
            if token not in found:
                found.append(token)
    for run in _CJK.findall(corpus):
        for part in _CJK_BREAK.split(run):
            part = part.strip()
            if 2 <= len(part) <= 8 and part not in _STOP and part not in found:
                found.append(part)
    return found[:limit]


@dataclass
class RequirementVerdict:
    """一条需求的核验结论。"""

    req_id: str
    title: str
    status: str  # completed | failed
    coverage: float  # 0.0 – 1.0
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "req_id": self.req_id,
            "title": self.title,
            "status": self.status,
            "coverage": round(self.coverage, 3),
            "matched": list(self.matched),
            "missing": list(self.missing),
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


def _snippet(text: str, token: str, width: int = 60) -> str:
    idx = text.find(token)
    if idx < 0:
        return ""
    start = max(0, idx - 20)
    return text[start : start + width].replace("\n", " ⏎ ")


def verify_requirement(
    *,
    req_id: str,
    title: str,
    description: str = "",
    acceptance_criteria: list[str] | None = None,
    artifact_text: str,
    threshold: float = 0.4,
) -> RequirementVerdict:
    """核验单条需求是否被交付产物覆盖。

    Args:
        artifact_text: 交付产物的**全文**（源码 + 文档）。
        threshold:     覆盖率下限；低于该值判 failed。
    """
    acs = [str(x) for x in (acceptance_criteria or []) if str(x).strip()]
    checkpoints = extract_checkpoints(title, description, *acs)
    if not checkpoints:
        return RequirementVerdict(
            req_id=req_id,
            title=title,
            status="completed",
            coverage=1.0,
            reason="需求未含可校验的关键点，按不阻塞处理",
        )

    body = artifact_text or ""
    matched, missing, evidence = [], [], []
    for token in checkpoints:
        if token in body:
            matched.append(token)
            snippet = _snippet(body, token)
            if snippet:
                evidence.append(snippet)
        else:
            missing.append(token)

    coverage = len(matched) / len(checkpoints)
    ok = coverage >= threshold
    reason = f"覆盖 {len(matched)}/{len(checkpoints)} 个关键点（{coverage:.0%}）" + (
        "" if ok else f"，低于阈值 {threshold:.0%}"
    )
    return RequirementVerdict(
        req_id=req_id,
        title=title,
        status="completed" if ok else "failed",
        coverage=coverage,
        matched=matched,
        missing=missing,
        evidence=evidence[:5],
        reason=reason,
    )
