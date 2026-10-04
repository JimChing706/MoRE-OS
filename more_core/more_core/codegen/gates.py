"""代码产出多维校验闸门 — 语法 / 逻辑 / 需求匹配。

设计目标（对应三大硬伤中的"产出正确性"）：

* **语法闸门**：交付前对每个代码块做真实解析（Python 用 ``compile``，其它语言
  用括号/引号配平 + 空实现检测），语法错误一律拦截。
* **逻辑闸门**：静态检测"假实现"——只有 ``pass`` / ``NotImplementedError`` /
  ``TODO`` 的函数体、超短空壳工程，避免把占位符当交付物。
* **需求匹配闸门**：从任务描述中抽取必须出现的标识符（反引号符号、函数/类名、
  ITD 的 REQ 关键词），计算覆盖率，低于阈值即拦截。

闸门是**确定性**的（无 LLM），符合项目规则"代码能回答的不要让模型回答"。
任一 blocking 失败都会让调用方把该次交付标记为不可信，而不是静默通过。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "GateFinding",
    "derive_required_symbols",
    "GateReport",
    "extract_code_blocks",
    "syntax_gate",
    "logic_gate",
    "requirement_gate",
    "run_gates",
]

_CODE_FENCE_RE = re.compile(r"```([A-Za-z0-9_+-]*)\s*\n(.*?)```", re.DOTALL)
_PY_LANGS = {"", "python", "py", "python3"}
_BRACE_LANGS = {"rust", "rs", "typescript", "ts", "tsx", "javascript", "js", "json", "go", "java", "c", "cpp"}
_STUB_PATTERNS = (
    re.compile(r"^\s*pass\s*$", re.MULTILINE),
    re.compile(r"\bNotImplementedError\b"),
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bFIXME\b", re.IGNORECASE),
    re.compile(r"placeholder", re.IGNORECASE),
    re.compile(r"^\s*unimplemented!\(\)\s*;?", re.MULTILINE),
)
# 需求匹配用的标识符噪声词（不作为必须命中项）
_STOPWORDS = {
    "the", "and", "for", "with", "use", "using", "code", "only", "output",
    "python", "rust", "typescript", "javascript", "function", "class", "def",
    "return", "import", "int", "str", "float", "bool", "list", "dict", "none",
    "write", "实现", "函数", "类", "只输出", "代码", "一个",
}


@dataclass
class GateFinding:
    """一条闸门结论。"""

    gate: str
    ok: bool
    blocking: bool = False
    detail: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "ok": self.ok,
            "blocking": self.blocking,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass
class GateReport:
    """一组闸门结论的汇总。"""

    findings: list[GateFinding] = field(default_factory=list)

    @property
    def blocking_failures(self) -> list[GateFinding]:
        return [f for f in self.findings if f.blocking and not f.ok]

    @property
    def warnings(self) -> list[GateFinding]:
        return [f for f in self.findings if not f.blocking and not f.ok]

    @property
    def passed(self) -> bool:
        return not self.blocking_failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "blocking_failures": [f.to_dict() for f in self.blocking_failures],
            "warnings": [f.to_dict() for f in self.warnings],
            "findings": [f.to_dict() for f in self.findings],
        }

    def summary(self) -> str:
        if self.passed and not self.warnings:
            return "all gates passed"
        parts = [f"{f.gate}: {f.detail}" for f in self.blocking_failures]
        parts += [f"warn {f.gate}: {f.detail}" for f in self.warnings]
        return "; ".join(parts) or "all gates passed"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return ``[(lang, code), ...]`` for every fenced block (lang lowercased)."""
    out: list[tuple[str, str]] = []
    for lang, body in _CODE_FENCE_RE.findall(text or ""):
        if body.strip():
            out.append(((lang or "").strip().lower(), body))
    return out


def _balanced(code: str) -> tuple[bool, str]:
    """Language-agnostic bracket/quote balance check (ignores strings/comments lightly)."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    in_str: str | None = None
    escape = False
    i = 0
    while i < len(code):
        ch = code[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
        elif ch in "\"'`":
            in_str = ch
        elif ch == "/" and i + 1 < len(code) and code[i + 1] == "/":
            nl = code.find("\n", i)
            i = len(code) if nl == -1 else nl
        elif ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False, f"unbalanced '{ch}'"
        i += 1
    if stack:
        return False, f"unclosed '{stack[-1]}'"
    if in_str:
        return False, "unterminated string literal"
    return True, ""


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------


def syntax_gate(text: str) -> GateFinding:
    """Blocking gate: every code block must parse/be well-formed."""
    blocks = extract_code_blocks(text)
    if not blocks:
        # 没有围栏代码块时，若整体像代码则按 Python 解析一次
        stripped = (text or "").strip()
        if not stripped:
            return GateFinding("syntax", False, True, "交付内容为空")
        if re.search(r"^\s*(def|class|import|from)\s", stripped, re.MULTILINE):
            blocks = [("python", stripped)]
        else:
            return GateFinding("syntax", True, False, "无代码块（纯文本交付）")

    problems: list[str] = []
    checked = 0
    for idx, (lang, code) in enumerate(blocks, 1):
        if lang in _PY_LANGS:
            checked += 1
            try:
                compile(code, f"<delivery:{idx}>", "exec")
            except SyntaxError as exc:
                problems.append(f"block#{idx} python syntax error: {exc.msg} (line {exc.lineno})")
            continue
        if lang in _BRACE_LANGS:
            checked += 1
            ok, why = _balanced(code)
            if not ok:
                problems.append(f"block#{idx} {lang} {why}")
            continue
    if problems:
        return GateFinding("syntax", False, True, "语法校验未通过", problems)
    return GateFinding("syntax", True, False, f"{checked} 个代码块语法通过")


def logic_gate(text: str, *, min_lines: int = 8) -> GateFinding:
    """Non-blocking unless the artifact is *only* stubs/placeholders.

    Catches the "文件名正确但内容是 placeholder" failure mode.
    """
    blocks = extract_code_blocks(text)
    body = "\n\n".join(code for _, code in blocks) or (text or "")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    stub_hits: list[str] = []
    for pat in _STUB_PATTERNS:
        for m in pat.finditer(body):
            frag = body[max(0, m.start() - 40): m.end() + 10].strip().replace("\n", " ⏎ ")
            stub_hits.append(frag[:110])

    # 统计"只有 pass 的函数体"
    empty_defs = 0
    for lang, code in blocks:
        if lang in _PY_LANGS:
            try:
                tree = ast.parse(code)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    stmts = [s for s in node.body if not isinstance(s, ast.Expr)]
                    if len(stmts) == 1 and isinstance(stmts[0], ast.Pass):
                        empty_defs += 1

    detail_parts = [f"{len(lines)} 行代码"]
    if stub_hits:
        detail_parts.append(f"{len(stub_hits)} 处占位/未实现标记")
    if empty_defs:
        detail_parts.append(f"{empty_defs} 个空函数体")

    blocking = bool(stub_hits and len(lines) < 60) or (empty_defs > 0 and len(lines) < 40)
    if blocking:
        return GateFinding(
            "logic", False, True,
            "产物被判为占位/空壳实现：" + "，".join(detail_parts),
            stub_hits[:5],
        )
    if lines and len(lines) < min_lines:
        return GateFinding("logic", False, False, f"产物较短（{len(lines)} 行），建议人工复核")
    return GateFinding("logic", True, False, "；".join(detail_parts))


_REQ_IDENT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{2,})`")
_DEF_RE = re.compile(r"\b(?:def|class|fn|struct|enum|interface|function)\s+([A-Za-z_][A-Za-z0-9_]*)")
_CALLISH_RE = re.compile(r"\b([a-z_][a-z0-9_]{3,})\s*\(")


#: 仅这些"代码式"写法才被视为必须存在的符号（避免把自然语言词当符号）
_SYMBOL_PATTERNS = (
    re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})`"),                 # `foo`
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\("),            # foo(
    re.compile(r"\b(?:def|class|fn|struct|enum|interface|function)\s+([A-Za-z_][A-Za-z0-9_]*)"),
)


def derive_required_symbols(query: str, *, limit: int = 6) -> list[str]:
    """从任务描述中派生"必须存在"的代码符号（D-2）。

    只认 ``foo(...)`` / ``` `foo` ``` / ``def foo`` 这类**代码式**写法，
    不把普通自然语言词当作符号，避免自动断言造成误杀。
    """
    found: list[str] = []
    for pattern in _SYMBOL_PATTERNS:
        for m in pattern.finditer(query or ""):
            name = m.group(1)
            low = name.lower()
            if low in _STOPWORDS or low in {"print", "len", "range", "int", "str", "list", "dict"}:
                continue
            if name not in found:
                found.append(name)
    return found[:limit]


def _required_symbols(query: str) -> list[str]:
    """Derive identifiers the answer must contain from the task description."""
    q = query or ""
    symbols: list[str] = []
    symbols += _REQ_IDENT_RE.findall(q)
    symbols += _DEF_RE.findall(q)
    # 形如 "写函数 merge_intervals(intervals)" 的自然语言描述
    for m in _CALLISH_RE.finditer(q):
        name = m.group(1)
        if name.lower() not in _STOPWORDS and not name.startswith(("http", "www")):
            symbols.append(name)
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        s = s.strip()
        low = s.lower()
        if low in _STOPWORDS or low in seen or len(s) < 3:
            continue
        seen.add(low)
        out.append(s)
    return out[:12]


def requirement_gate(text: str, query: str, *, threshold: float = 0.6) -> GateFinding:
    """需求匹配度：必须标识符在产物中的覆盖率。"""
    required = _required_symbols(query)
    if not required:
        return GateFinding("requirement", True, False, "任务描述未含可校验的标识符")
    body = text or ""
    missing = [s for s in required if s not in body]
    covered = len(required) - len(missing)
    ratio = covered / len(required)
    detail = f"需求符号覆盖 {covered}/{len(required)} = {ratio:.0%}"
    if ratio < threshold:
        return GateFinding("requirement", False, True, detail, [f"缺少: {m}" for m in missing[:6]])
    return GateFinding("requirement", True, False, detail)


def run_gates(
    text: str,
    *,
    query: str = "",
    require_logic: bool = False,
) -> GateReport:
    """Run the full gate set over a candidate delivery artifact."""
    report = GateReport()
    report.findings.append(syntax_gate(text))
    logic = logic_gate(text)
    if not require_logic:
        # 纯问答类任务不因"短"而拦截，但占位/空壳仍然拦截
        logic.blocking = bool(logic.evidence)
    report.findings.append(logic)
    if query:
        report.findings.append(requirement_gate(text, query))
    return report
