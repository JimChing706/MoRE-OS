"""Import Task Document — rigorous Markdown task definition format.

Parses, validates, and generates Import Task Documents (ITD) for the MoRE OS
pipeline. An ITD is a Markdown file with YAML frontmatter that defines:

- Task metadata, type, priority, pipeline hints
- Formal requirements with acceptance criteria
- Deliverable contract (what "done" means)
- Kill criteria (when to abort)
- Resource budget (tokens, time, iterations)
- Context and constraints

Design principles (per CLAUDE.md):
- R2: 诚实铁律 — each deliverable dimension must be measurable
- R9: 迭代闭合 — every ITD converges toward a contract
- R14: 多维结论完整性 — contract forces multi-dimensional output
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .deliverable import (
    DeliverableKind,
    KillCriterion,
    KillSeverity,
    TaskExpectation,
)
from .types import TaskRequest, TaskType


# ---------------------------------------------------------------------------
# ITD-specific enums
# ---------------------------------------------------------------------------


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PipelineMode(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_TASK_TYPES: set[str] = {e.value for e in TaskType}
VALID_DELIVERABLE_KINDS: set[str] = {e.value for e in DeliverableKind}
VALID_PRIORITIES: set[str] = {e.value for e in Priority}
VALID_PIPELINE_MODES: set[str] = {e.value for e in PipelineMode}

# Regex to extract requirement items
_REQ_PATTERN = re.compile(
    r"^##\s+(REQ-\d{3,}):\s+(.+)$",
    re.MULTILINE,
)
_REQ_AC_PATTERN = re.compile(r"^- \[([ x])\]\s+(.+)$", re.MULTILINE)

# Regex to extract kill criteria table rows
_KC_TABLE_ROW = re.compile(
    r"^\|\s*([\w-]+)\s*\|\s*(.+?)\s*\|\s*(fatal|critical|warning)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$",
    re.MULTILINE,
)

# Regex to extract quality gates table rows
_QG_TABLE_ROW = re.compile(
    r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$",
    re.MULTILINE,
)

# Frontmatter delimiter
_FM_DELIM = "---"

# Mode B detection: # title + ## REQ-xxx patterns without frontmatter
_MODE_B_TITLE_PATTERN = re.compile(r"^#\s+(.+?)$", re.MULTILINE)
_MODE_B_HAS_REQ = re.compile(r"^##\s+REQ-\d{3,}:", re.MULTILINE)

# Mode C detection: natural language prompt matching pattern
_MODE_C_DETECT_PATTERN = re.compile(
    r"^通过.*?任务导入.*?启动.*?(?:具体执行要求|五章详细技术要求|以下为五?章|要求如下|详细开发要求).*?"
    r"(?:(?:\n|.)*?第[1-5]章|(?:\n|.)*?(?:^|\n)\s*[1-5][、.．)])",
    re.MULTILINE | re.DOTALL,
)
_MODE_C_REQ_EXTRACT = re.compile(
    r"(?:^|\n)\s*([1-5])[、.．)]\s*([^\n]+)",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RequirementItem:
    """A single formal requirement."""

    id: str  # REQ-001
    title: str
    description: str
    priority: Priority = Priority.MEDIUM
    acceptance_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority.value,
            "acceptance_criteria": self.acceptance_criteria,
        }


@dataclass
class QualityGate:
    """A named quality threshold."""

    name: str
    threshold: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "threshold": self.threshold}


@dataclass
class ImportKillCriterion:
    """A structured kill criterion from an ITD."""

    id: str  # KC-001
    condition: str
    severity: str  # fatal | critical | warning
    timeline: str  # immediate | end-of-run
    fallback: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "condition": self.condition,
            "severity": self.severity,
            "timeline": self.timeline,
            "fallback": self.fallback,
        }


@dataclass
class ResourceBudget:
    """Token, time, and iteration budget."""

    estimated_tokens: int = 0
    estimated_duration_min: int = 0
    max_iterations: int = 10
    per_provider: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimated_tokens": self.estimated_tokens,
            "estimated_duration_min": self.estimated_duration_min,
            "max_iterations": self.max_iterations,
            "per_provider": self.per_provider,
        }


@dataclass
class ImportTaskDocument:
    """The full structured representation of an Import Task Document."""

    # Frontmatter (metadata)
    title: str = ""
    version: str = "1.0.0"
    author: str = ""
    created: str = ""
    type: str = TaskType.NLP_TASK.value
    plugin_type: str | None = None
    priority: str = Priority.MEDIUM.value
    deliverable_kind: str = DeliverableKind.CUSTOM.value
    tags: list[str] = field(default_factory=list)
    estimated_hours: float = 0.0
    depends_on: list[str] = field(default_factory=list)

    # Pipeline hints
    pipeline_mode: str | None = None
    pipeline_prepend: list[str] = field(default_factory=list)
    pipeline_append: list[str] = field(default_factory=list)
    pipeline_skip: list[str] = field(default_factory=list)

    # Execution hints
    target_confidence: float = 60.0
    max_iterations: int = 10
    timeout_s: float = 60.0
    allow_self_improvement: bool = False
    require_metacognitive: bool = False
    kill_on_diverge: bool = True

    # Body sections
    summary: str = ""
    requirements: list[RequirementItem] = field(default_factory=list)

    # Deliverable contract
    contract_kind: str = DeliverableKind.CUSTOM.value
    contract_required_dimensions: list[str] = field(default_factory=list)
    contract_quality_gates: list[QualityGate] = field(default_factory=list)
    contract_acceptance_criteria: list[str] = field(default_factory=list)
    contract_min_output_length: int = 100

    # Kill criteria
    kill_criteria: list[ImportKillCriterion] = field(default_factory=list)

    # Resource budget
    budget: ResourceBudget = field(default_factory=ResourceBudget)

    # Context
    context_background: str = ""
    context_constraints: list[str] = field(default_factory=list)
    context_references: list[str] = field(default_factory=list)

    # Related docs
    related_documents: list[str] = field(default_factory=list)

    # Raw frontmatter dict (for round-trip preservation)
    _raw_frontmatter: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": {
                "title": self.title,
                "version": self.version,
                "author": self.author,
                "created": self.created,
                "type": self.type,
                "plugin_type": self.plugin_type,
                "priority": self.priority,
                "deliverable_kind": self.deliverable_kind,
                "tags": self.tags,
                "estimated_hours": self.estimated_hours,
                "depends_on": self.depends_on,
                "pipeline": {
                    "mode": self.pipeline_mode,
                    "prepend": self.pipeline_prepend,
                    "append": self.pipeline_append,
                    "skip": self.pipeline_skip,
                },
                "target_confidence": self.target_confidence,
                "max_iterations": self.max_iterations,
                "timeout_s": self.timeout_s,
                "allow_self_improvement": self.allow_self_improvement,
                "require_metacognitive": self.require_metacognitive,
                "kill_on_diverge": self.kill_on_diverge,
            },
            "summary": self.summary,
            "requirements": [r.to_dict() for r in self.requirements],
            "deliverable_contract": {
                "kind": self.contract_kind,
                "required_dimensions": self.contract_required_dimensions,
                "quality_gates": [g.to_dict() for g in self.contract_quality_gates],
                "acceptance_criteria": self.contract_acceptance_criteria,
                "min_output_length": self.contract_min_output_length,
            },
            "kill_criteria": [k.to_dict() for k in self.kill_criteria],
            "resource_budget": self.budget.to_dict(),
            "context": {
                "background": self.context_background,
                "constraints": self.context_constraints,
                "references": self.context_references,
            },
            "related_documents": self.related_documents,
        }

    def to_task_request(self) -> TaskRequest:
        """Convert this ITD into a TaskRequest for MoRE OS execution."""
        expectation = TaskExpectation.default_for(
            DeliverableKind(self.contract_kind),
        )
        expectation.contract.required_dimensions = self.contract_required_dimensions
        expectation.contract.acceptance_criteria = self.contract_acceptance_criteria
        expectation.target_confidence = self.target_confidence
        expectation.max_iterations = self.max_iterations
        expectation.timeout_s = self.timeout_s

        if self.kill_criteria:
            expectation.kill_criteria = [
                KillCriterion(
                    condition=k.condition,
                    severity=KillSeverity(k.severity),
                    timeline=k.timeline,
                    fallback=k.fallback,
                )
                for k in self.kill_criteria
            ]

        return TaskRequest(
            type=TaskType(self.type),
            plugin_type=self.plugin_type,
            query=self.summary,
            context={
                "_itd_source": {
                    "title": self.title,
                    "version": self.version,
                    "requirements": [r.id for r in self.requirements],
                },
            },
            require_metacognitive_monitoring=self.require_metacognitive,
            allow_self_improvement=self.allow_self_improvement,
            timeout_s=self.timeout_s,
            deliverable_kind=self.deliverable_kind,
            expectation=expectation.to_dict(),
        )

    def to_yaml_frontmatter(self) -> str:
        """Export only the frontmatter as a compact YAML-like string."""
        lines = ["---"]
        lines.append(f"title: {self.title}")
        lines.append(f"version: {self.version}")
        lines.append(f"author: {self.author}")
        lines.append(f"created: {self.created}")
        lines.append(f"type: {self.type}")
        lines.append(f"priority: {self.priority}")
        lines.append(f"deliverable_kind: {self.deliverable_kind}")
        lines.append(f"tags: {json.dumps(self.tags)}")
        if self.estimated_hours:
            lines.append(f"estimated_hours: {self.estimated_hours}")
        if self.depends_on:
            lines.append(f"depends_on: {json.dumps(self.depends_on)}")
        if self.pipeline_mode:
            lines.append(f"pipeline_mode: {self.pipeline_mode}")
        lines.append("---")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class ImportTaskError(Exception):
    """Raised when an ITD document fails validation."""


class ImportTaskParser:
    """Parses an Import Task Document from Markdown text."""

    def parse(self, text: str, filename: str = "") -> ImportTaskDocument:
        """Parse ITD Markdown into an ImportTaskDocument.

        Raises ImportTaskError on fatal validation failures.
        """
        mode_id, warning_label = self._detect_mode(text)
        if mode_id == "B":
            text = self._synthesize_mode_b_frontmatter(text)
        elif mode_id == "C":
            text = self._synthesize_mode_c_frontmatter(text)

        frontmatter, body = self._split_frontmatter(text)

        doc = ImportTaskDocument()
        doc._raw_frontmatter = frontmatter
        doc.title = frontmatter.get("title", "")
        doc.version = str(frontmatter.get("version", "1.0.0"))
        doc.author = str(frontmatter.get("author", ""))
        doc.created = str(frontmatter.get("created", ""))
        doc.type = str(frontmatter.get("type", TaskType.NLP_TASK.value))
        doc.plugin_type = frontmatter.get("plugin_type")
        doc.priority = str(frontmatter.get("priority", Priority.MEDIUM.value))
        doc.deliverable_kind = str(
            frontmatter.get("deliverable_kind", DeliverableKind.CUSTOM.value),
        )

        raw_tags = frontmatter.get("tags", [])
        doc.tags = list(raw_tags) if isinstance(raw_tags, list) else [str(raw_tags)]

        doc.estimated_hours = float(frontmatter.get("estimated_hours", 0) or 0)

        raw_deps = frontmatter.get("depends_on", [])
        doc.depends_on = list(raw_deps) if isinstance(raw_deps, list) else []

        pipeline = frontmatter.get("pipeline", {}) or {}
        if isinstance(pipeline, dict):
            doc.pipeline_mode = pipeline.get("mode")
            doc.pipeline_prepend = list(pipeline.get("prepend", []))
            doc.pipeline_append = list(pipeline.get("append", []))
            doc.pipeline_skip = list(pipeline.get("skip", []))
        elif isinstance(pipeline, str):
            doc.pipeline_mode = pipeline

        doc.target_confidence = float(
            frontmatter.get("target_confidence", 60.0) or 60.0,
        )
        doc.max_iterations = int(frontmatter.get("max_iterations", 10) or 10)
        doc.timeout_s = float(frontmatter.get("timeout_s", 60.0) or 60.0)
        doc.allow_self_improvement = bool(
            frontmatter.get("allow_self_improvement", False),
        )
        doc.require_metacognitive = bool(
            frontmatter.get("require_metacognitive", False),
        )
        doc.kill_on_diverge = bool(frontmatter.get("kill_on_diverge", True))

        # Parse body sections
        sections = self._extract_sections(body)

        doc.summary = self._get_section_text(sections, "Executive Summary", "")

        doc.requirements = self._parse_requirements(
            self._get_section_text(sections, "Requirements", ""),
        )

        contract_text = self._get_section_text(
            sections,
            "Deliverable Contract",
            "",
        )
        self._parse_contract_into(doc, contract_text)

        kc_text = self._get_section_text(sections, "Kill Criteria", "")
        doc.kill_criteria = self._parse_kill_criteria(kc_text)

        budget_text = self._get_section_text(sections, "Resource Budget", "")
        self._parse_budget_into(doc, budget_text)

        context_text = self._get_section_text(sections, "Context and Constraints", "")
        self._parse_context_into(doc, context_text)

        doc.related_documents = self._parse_related_docs(
            self._get_section_text(sections, "Related Documents", ""),
        )

        if "_warnings" not in doc._raw_frontmatter:
            doc._raw_frontmatter["_warnings"] = []
        doc._raw_frontmatter["_warnings"].insert(0, warning_label)

        # Validate after full parse
        self._validate(doc)

        return doc

    # ------------------------------------------------------------------
    # Multi-mode detection & synthesis
    # ------------------------------------------------------------------

    def _detect_mode(self, text: str) -> tuple[str, str]:
        """Detect input mode.

        Returns:
            tuple: (mode_id, warning_label)
                mode_id: 'A' | 'B' | 'C'
                warning_label: '模式A/B' | '模式C'
        """
        stripped = text.strip()
        if stripped.startswith(_FM_DELIM):
            return ("A", "模式A/B")
        if _MODE_C_DETECT_PATTERN.search(stripped):
            return ("C", "模式C")
        if _MODE_B_HAS_REQ.search(stripped):
            return ("B", "模式A/B")
        return ("A", "模式A/B")

    def _synthesize_mode_b_frontmatter(self, text: str) -> str:
        """Synthesize frontmatter for Mode B: # title + ## REQ-xxx + - [x] AC."""
        stripped = text.strip()
        title_match = _MODE_B_TITLE_PATTERN.search(stripped)
        title = title_match.group(1).strip() if title_match else "Untitled Mode B Task"

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        frontmatter_lines = [
            "---",
            f"title: {title}",
            "version: 1.0.0",
            "author: mode_b_synthesis",
            f"created: {now_iso}",
            "type: nlp_task",
            "priority: medium",
            "deliverable_kind: custom",
            "tags: [mode_b, auto_generated]",
            "target_confidence: 60.0",
            "max_iterations: 10",
            "timeout_s: 60.0",
            "---",
            "",
        ]

        body_parts: list[str] = []
        lines_iter = iter(stripped.split("\n"))
        h1_consumed = False
        for line in lines_iter:
            if not h1_consumed and re.match(r"^#\s+.+$", line.strip()):
                h1_consumed = True
                body_parts.append("# Executive Summary")
                body_parts.append("")
                body_parts.append(title)
                body_parts.append("")
                body_parts.append("# Requirements")
                body_parts.append("")
                continue
            body_parts.append(line)

        merged_body = "\n".join(body_parts)
        if "# Requirements" not in merged_body:
            merged_body = merged_body.rstrip() + "\n\n# Requirements\n\n"

        return "\n".join(frontmatter_lines) + merged_body

    def _synthesize_mode_c_frontmatter(self, text: str) -> str:
        """Synthesize frontmatter and full ITD body for Mode C natural language prompt."""
        stripped = text.strip()
        md5_hash = hashlib.md5(stripped.encode("utf-8")).hexdigest()[:6]
        title = f"任务导入自动生成_{md5_hash}"

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        req_matches = _MODE_C_REQ_EXTRACT.findall(stripped)
        req_texts: list[str] = []
        for m in req_matches:
            req_texts.append(m[1].strip())

        requirements_block = ""
        for idx, rtext in enumerate(req_texts[:5], start=1):
            req_id = f"REQ-{idx:03d}"
            ac_text = rtext[:80]
            requirements_block += (
                f"## {req_id}: 自动提取需求{idx}\n"
                f"**Priority:** MEDIUM\n"
                f"**Description:** {rtext}\n"
                f"\n"
                f"**Acceptance Criteria:**\n"
                f"- [x] {ac_text}\n"
                f"\n"
            )

        frontmatter_lines = [
            "---",
            f"title: {title}",
            "version: 1.0.0",
            "author: mode_c_synthesis",
            f"created: {now_iso}",
            "type: nlp_task",
            "priority: medium",
            "deliverable_kind: custom",
            "tags: [mode_c, auto_generated]",
            "target_confidence: 60.0",
            "max_iterations: 10",
            "timeout_s: 300.0",
            "---",
            "",
        ]

        summary = stripped[:200]

        kill_criteria_block = (
            "# Kill Criteria\n\n"
            "| ID | Condition | Severity | Timeline | Fallback |\n"
            "|----|-----------|----------|----------|----------|\n"
            "| KC-001 | 执行超时超过300秒未返回结果 | fatal | immediate | 终止任务并记录超时日志 |\n\n"
        )

        contract_block = (
            "# Deliverable Contract\n\n"
            "**Kind:** custom\n"
            "**Required Dimensions:** core_output\n"
            "**Minimum Output Length:** 100\n\n"
            "**Acceptance Criteria:**\n"
            "- [ ] 至少包含5条需求的处理结果\n\n"
        )

        merged = (
            "\n".join(frontmatter_lines)
            + "# Executive Summary\n\n"
            + summary
            + "\n\n"
            + "# Requirements\n\n"
            + requirements_block
            + contract_block
            + kill_criteria_block
            + "# Resource Budget\n\n"
            + "**Estimated Tokens:** 5000\n"
            + "**Estimated Duration:** 15 minutes\n"
            + "**Max Iterations:** 10\n\n"
        )

        return merged

    # ------------------------------------------------------------------
    # Frontmatter
    # ------------------------------------------------------------------

    def _split_frontmatter(self, text: str) -> tuple[dict[str, Any], str]:
        """Split text into frontmatter dict and body string."""
        text = text.strip()
        if not text.startswith(_FM_DELIM):
            return {}, text

        parts = text.split(_FM_DELIM, 2)
        if len(parts) < 3:
            return {}, parts[-1] if parts else ""

        raw = parts[1].strip()
        body = parts[2].strip()
        return self._parse_yaml_like(raw), body

    def _parse_yaml_like(self, text: str) -> dict[str, Any]:
        """Parse frontmatter without a YAML dependency.

        Handles both flat and nested (2-space indented) structures.
        """
        result: dict[str, Any] = {}
        stack: list[tuple[int, dict[str, Any]]] = [(0, result)]

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue

            indent = len(line) - len(line.lstrip())
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            # Pop stack back to correct indent level
            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()
            current = stack[-1][1]

            if value:
                parsed = self._parse_scalar(value)
                current[key] = parsed
            else:
                new_dict: dict[str, Any] = {}
                current[key] = new_dict
                stack.append((indent, new_dict))

        return result

    def _parse_scalar(self, value: str) -> Any:
        """Parse a scalar YAML value."""
        if value.startswith("[") and value.endswith("]"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                items = value.strip("[]").split(",")
                return [v.strip().strip("\"'") for v in items]
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        if value in ("null", "~"):
            return None
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return value

    # ------------------------------------------------------------------
    # Section extraction
    # ------------------------------------------------------------------

    def _extract_sections(self, body: str) -> dict[str, str]:
        """Split body into sections by top-level headings."""
        sections: dict[str, str] = {}
        current_key = ""
        current_lines: list[str] = []

        for line in body.split("\n"):
            h1_match = re.match(r"^#\s+(.+)$", line.strip())
            if h1_match:
                if current_key and current_lines:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = h1_match.group(1).strip()
                current_lines = []
            elif current_key:
                current_lines.append(line)

        if current_key and current_lines:
            sections[current_key] = "\n".join(current_lines).strip()

        return sections

    def _extract_h2_sections(self, text: str) -> dict[str, str]:
        """Split text into subsections by H2-level headings."""
        sections: dict[str, str] = {}
        current_key = ""
        current_lines: list[str] = []

        for line in text.split("\n"):
            h2_match = re.match(r"^##\s+(.+)$", line.strip())
            if h2_match:
                if current_key and current_lines:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = h2_match.group(1).strip()
                current_lines = []
            elif current_key:
                current_lines.append(line)

        if current_key and current_lines:
            sections[current_key] = "\n".join(current_lines).strip()

        return sections

    def _get_section_text(
        self,
        sections: dict[str, str],
        name: str,
        default: str = "",
    ) -> str:
        """Get section by display name, normalizing for aliases."""
        for key, value in sections.items():
            if key.lower() == name.lower():
                return value
        return default

    # ------------------------------------------------------------------
    # Requirements parsing
    # ------------------------------------------------------------------

    def _parse_requirements(self, text: str) -> list[RequirementItem]:
        """Parse requirement items from the Requirements section.

        Supports the format:
        ## REQ-NNN: Title
        **Priority:** HIGH
        **Description:** ...

        **Acceptance Criteria:**
        - [ ] criterion 1
        - [x] criterion 2
        """
        if not text.strip():
            return []

        items: list[RequirementItem] = []
        blocks = re.split(r"\n(?=##\s+REQ-\d)", text.strip())

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            m = re.match(r"^##\s+(REQ-\d{3,}):\s+(.+?)(?:\n|$)", block)
            if not m:
                continue
            req_id = m.group(1).strip()
            title = m.group(2).strip()

            priority = Priority.MEDIUM
            pm = re.search(r"\*\*Priority:\*\*\s*(\w+)", block)
            if pm:
                try:
                    priority = Priority(pm.group(1).lower())
                except ValueError:
                    pass

            desc_m = re.search(r"\*\*Description:\*\*\s*(.+?)(?:\n\*\*|\Z)", block, re.DOTALL)
            description = desc_m.group(1).strip() if desc_m else ""

            acs: list[str] = []
            in_ac = False
            for line in block.split("\n"):
                ac_m = re.match(r"^- \[([ x])\]\s+(.+)$", line.strip())
                if ac_m:
                    in_ac = True
                    acs.append(ac_m.group(2).strip())
                elif in_ac and line.strip() and not line.strip().startswith("-"):
                    in_ac = False

            items.append(
                RequirementItem(
                    id=req_id,
                    title=title,
                    description=description,
                    priority=priority,
                    acceptance_criteria=acs,
                )
            )

        return items

    # ------------------------------------------------------------------
    # Deliverable contract parsing
    # ------------------------------------------------------------------

    def _parse_contract_into(self, doc: ImportTaskDocument, text: str) -> None:
        """Parse the Deliverable Contract section into the document."""
        if not text.strip():
            return

        kind_m = re.search(r"\*\*Kind:\*\*\s*(\w+)", text)
        if kind_m:
            doc.contract_kind = kind_m.group(1).lower()

        dims_m = re.search(
            r"\*\*Required Dimensions:\*\*\s*(.+?)(?:\n|$)",
            text,
        )
        if dims_m:
            raw = dims_m.group(1).strip()
            doc.contract_required_dimensions = [d.strip() for d in raw.split(",") if d.strip()]

        min_len_m = re.search(r"\*\*Minimum Output Length:\*\*\s*(\d+)", text)
        if min_len_m:
            doc.contract_min_output_length = int(min_len_m.group(1))

        # Quality gates table
        in_qg = False
        for line in text.split("\n"):
            if line.strip().startswith("| Gate") and "Threshold" in line:
                in_qg = True
                continue
            if in_qg and line.strip().startswith("|---"):
                continue
            if in_qg:
                qg_m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", line.strip())
                if qg_m:
                    qg_name = qg_m.group(1).strip()
                    qg_val = qg_m.group(2).strip()
                    if qg_name and qg_name != "Gate":
                        doc.contract_quality_gates.append(
                            QualityGate(name=qg_name, threshold=qg_val),
                        )
                elif line.strip() and not line.strip().startswith("|"):
                    in_qg = False

        # Acceptance criteria from "**Acceptance Criteria:**" section
        in_ac = False
        for line in text.split("\n"):
            if re.match(r"^\*\*Acceptance Criteria:\*\*", line.strip()):
                in_ac = True
                continue
            if in_ac:
                ac_m = re.match(r"^- \[([ x])\]\s+(.+)$", line.strip())
                if ac_m:
                    doc.contract_acceptance_criteria.append(ac_m.group(2).strip())
                elif line.strip() and not line.strip().startswith("-"):
                    in_ac = False

    # ------------------------------------------------------------------
    # Kill criteria parsing
    # ------------------------------------------------------------------

    def _parse_kill_criteria(self, text: str) -> list[ImportKillCriterion]:
        """Parse the Kill Criteria table into structured criteria."""
        if not text.strip():
            return []

        criteria: list[ImportKillCriterion] = []
        in_table = False

        for line in text.split("\n"):
            if line.strip().startswith("| ID") and "Condition" in line:
                in_table = True
                continue
            if in_table and line.strip().startswith("|---"):
                continue
            if in_table:
                row_m = re.match(
                    r"^\|\s*([\w-]+)\s*\|\s*(.+?)\s*\|\s*(fatal|critical|warning)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$",
                    line.strip(),
                )
                if row_m:
                    criteria.append(
                        ImportKillCriterion(
                            id=row_m.group(1).strip(),
                            condition=row_m.group(2).strip(),
                            severity=row_m.group(3).strip(),
                            timeline=row_m.group(4).strip(),
                            fallback=row_m.group(5).strip(),
                        )
                    )
                elif line.strip() and not line.strip().startswith("|"):
                    in_table = False

        return criteria

    # ------------------------------------------------------------------
    # Resource budget parsing
    # ------------------------------------------------------------------

    def _parse_budget_into(self, doc: ImportTaskDocument, text: str) -> None:
        """Parse the Resource Budget section."""
        if not text.strip():
            return

        tok_m = re.search(r"\*\*Estimated Tokens:\*\*\s*([\d,]+)", text)
        if tok_m:
            doc.budget.estimated_tokens = int(tok_m.group(1).replace(",", ""))

        dur_m = re.search(r"\*\*Estimated Duration:\*\*\s*(\d+)", text)
        if dur_m:
            doc.budget.estimated_duration_min = int(dur_m.group(1))

        iter_m = re.search(r"\*\*Max Iterations:\*\*\s*(\d+)", text)
        if iter_m:
            doc.budget.max_iterations = int(iter_m.group(1))

    # ------------------------------------------------------------------
    # Context parsing
    # ------------------------------------------------------------------

    def _parse_context_into(self, doc: ImportTaskDocument, text: str) -> None:
        """Parse the Context and Constraints section."""
        if not text.strip():
            return

        sub_sections = self._extract_h2_sections(text)
        doc.context_background = sub_sections.get("Background", "")

        constraints_text = sub_sections.get("Constraints", "")
        doc.context_constraints = [
            line.strip().lstrip("-").strip()
            for line in constraints_text.split("\n")
            if line.strip().startswith("-")
        ]

        refs_text = sub_sections.get("References", "")
        doc.context_references = [
            line.strip("- ").strip()
            for line in refs_text.split("\n")
            if line.strip().startswith("-")
        ]

    # ------------------------------------------------------------------
    # Related documents
    # ------------------------------------------------------------------

    def _parse_related_docs(self, text: str) -> list[str]:
        """Parse the Related Documents section."""
        if not text.strip():
            return []
        return [
            line.strip("- ").strip() for line in text.split("\n") if line.strip().startswith("-")
        ]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, doc: ImportTaskDocument) -> None:
        """Validate the parsed ITD document.

        Raises ImportTaskError for fatal violations, collects warnings
        in doc._raw_frontmatter["_warnings"].
        """
        errors: list[str] = []
        warnings: list[str] = []

        # R001: title is present and non-empty
        if not doc.title:
            errors.append("R002: title is required and must be non-empty")

        # R003: type is a valid TaskType
        if doc.type not in VALID_TASK_TYPES:
            errors.append(
                f"R003: type '{doc.type}' is not a valid TaskType. "
                f"Valid values: {', '.join(sorted(VALID_TASK_TYPES))}",
            )

        # R004: priority is valid
        if doc.priority not in VALID_PRIORITIES:
            errors.append(
                f"R004: priority '{doc.priority}' is not valid. Valid values: high, medium, low",
            )

        # R005: deliverable_kind is valid
        if doc.deliverable_kind not in VALID_DELIVERABLE_KINDS:
            warnings.append(
                f"R005: deliverable_kind '{doc.deliverable_kind}' is not standard",
            )

        # R006: tags is non-empty
        if not doc.tags:
            warnings.append("R006: tags list is empty; consider adding at least one tag")

        # R007: Executive Summary exists
        if not doc.summary.strip():
            warnings.append("R007: Executive Summary section is empty or missing")

        # R008: Deliverable Contract exists
        if not doc.contract_kind:
            warnings.append("R008: Deliverable Contract section is missing")

        # R009: at least one acceptance criterion
        if not doc.contract_acceptance_criteria:
            warnings.append(
                "R009: no acceptance criteria defined in Deliverable Contract",
            )

        # R010: pipeline mode is valid
        if doc.pipeline_mode and doc.pipeline_mode not in VALID_PIPELINE_MODES:
            warnings.append(
                f"R010: pipeline.mode '{doc.pipeline_mode}' is not valid. "
                f"Valid values: quick, standard, deep",
            )

        # R011: unique REQ IDs
        req_ids = [r.id for r in doc.requirements]
        if len(req_ids) != len(set(req_ids)):
            errors.append("R011: duplicate REQ-XXX IDs found")

        # R012: empty requirements list is a warning
        if not doc.requirements:
            warnings.append("R012: no requirements defined")

        # R013: created date is recommended
        if not doc.created:
            warnings.append("R013: created date is recommended (use ISO 8601 format)")

        # R014: author is recommended
        if not doc.author:
            warnings.append("R014: author is recommended")

        # Store warnings
        existing_warnings = doc._raw_frontmatter.get("_warnings", [])
        if existing_warnings:
            doc._raw_frontmatter["_warnings"] = [existing_warnings[0]] + warnings
        else:
            doc._raw_frontmatter["_warnings"] = warnings
        doc._raw_frontmatter["_errors"] = errors

        if errors:
            raise ImportTaskError(
                f"ITD validation failed with {len(errors)} fatal error(s):\n"
                + "\n".join(f"  - {e}" for e in errors),
            )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class ImportTaskGenerator:
    """Generates well-formatted ITD Markdown from structured data."""

    def generate(self, doc: ImportTaskDocument) -> str:
        """Generate an ITD Markdown string from a structured document."""
        parts: list[str] = []

        # Frontmatter
        parts.append(self._render_frontmatter(doc))
        parts.append("")

        # Executive Summary
        parts.append("# Executive Summary")
        parts.append("")
        parts.append(doc.summary.strip() or "TODO: add summary")
        parts.append("")

        # Requirements
        if doc.requirements:
            parts.append("# Requirements")
            parts.append("")
            for req in doc.requirements:
                parts.append(f"## {req.id}: {req.title}")
                parts.append(f"**Priority:** {req.priority.value.upper()}")
                parts.append(f"**Description:** {req.description}")
                parts.append("")
                parts.append("**Acceptance Criteria:**")
                for ac in req.acceptance_criteria:
                    parts.append(f"- [ ] {ac}")
                parts.append("")
        else:
            parts.append("# Requirements")
            parts.append("")
            parts.append("TODO: define requirements")
            parts.append("")

        # Deliverable Contract
        parts.append("# Deliverable Contract")
        parts.append("")
        parts.append(f"**Kind:** {doc.contract_kind}")
        if doc.contract_required_dimensions:
            parts.append(
                f"**Required Dimensions:** {', '.join(doc.contract_required_dimensions)}",
            )
        parts.append(f"**Minimum Output Length:** {doc.contract_min_output_length}")
        parts.append("")
        if doc.contract_quality_gates:
            parts.append("**Quality Gates:**")
            parts.append("| Gate | Threshold |")
            parts.append("|------|-----------|")
            for g in doc.contract_quality_gates:
                parts.append(f"| {g.name} | {g.threshold} |")
            parts.append("")
        if doc.contract_acceptance_criteria:
            parts.append("**Acceptance Criteria:**")
            parts.append("")
            for i, ac in enumerate(doc.contract_acceptance_criteria, 1):
                parts.append(f"- [ ] {ac}")
            parts.append("")
        else:
            parts.append("**Acceptance Criteria:**")
            parts.append("- [ ] TODO: define acceptance criteria")
            parts.append("")

        # Kill Criteria
        if doc.kill_criteria:
            parts.append("# Kill Criteria")
            parts.append("")
            parts.append("| ID | Condition | Severity | Timeline | Fallback |")
            parts.append("|----|-----------|----------|----------|----------|")
            for kc in doc.kill_criteria:
                parts.append(
                    f"| {kc.id} | {kc.condition} | {kc.severity} | {kc.timeline} | {kc.fallback} |",
                )
            parts.append("")
        else:
            parts.append("# Kill Criteria")
            parts.append("")
            parts.append("None defined.")
            parts.append("")

        # Resource Budget
        parts.append("# Resource Budget")
        parts.append("")
        if doc.budget.estimated_tokens:
            parts.append(f"**Estimated Tokens:** {doc.budget.estimated_tokens:,}")
        if doc.budget.estimated_duration_min:
            parts.append(f"**Estimated Duration:** {doc.budget.estimated_duration_min} minutes")
        parts.append(f"**Max Iterations:** {doc.budget.max_iterations}")
        parts.append("")

        # Context and Constraints
        has_context = any(
            [
                doc.context_background,
                doc.context_constraints,
                doc.context_references,
            ]
        )
        if has_context:
            parts.append("# Context and Constraints")
            parts.append("")
            if doc.context_background:
                parts.append("## Background")
                parts.append("")
                parts.append(doc.context_background.strip())
                parts.append("")
            if doc.context_constraints:
                parts.append("## Constraints")
                parts.append("")
                for c in doc.context_constraints:
                    parts.append(f"- {c}")
                parts.append("")
            if doc.context_references:
                parts.append("## References")
                parts.append("")
                for r in doc.context_references:
                    parts.append(f"- {r}")
                parts.append("")

        # Related Documents
        if doc.related_documents:
            parts.append("# Related Documents")
            parts.append("")
            for rd in doc.related_documents:
                parts.append(f"- {rd}")
            parts.append("")

        return "\n".join(parts)

    def _render_frontmatter(self, doc: ImportTaskDocument) -> str:
        """Render the YAML frontmatter string."""
        lines = ["---"]
        lines.append(f"title: {doc.title}")
        lines.append(f"version: {doc.version}")
        lines.append(f"author: {doc.author}")
        lines.append(f"created: {doc.created}")
        lines.append(f"type: {doc.type}")
        if doc.plugin_type:
            lines.append(f"plugin_type: {doc.plugin_type}")
        lines.append(f"priority: {doc.priority}")
        lines.append(f"deliverable_kind: {doc.deliverable_kind}")
        lines.append(f"tags: {json.dumps(doc.tags)}")
        if doc.estimated_hours:
            lines.append(f"estimated_hours: {doc.estimated_hours}")
        if doc.depends_on:
            lines.append(f"depends_on: {json.dumps(doc.depends_on)}")
        if any([doc.pipeline_mode, doc.pipeline_prepend, doc.pipeline_append, doc.pipeline_skip]):
            lines.append("pipeline:")
            if doc.pipeline_mode:
                lines.append(f"  mode: {doc.pipeline_mode}")
            if doc.pipeline_prepend:
                lines.append(f"  prepend: {json.dumps(doc.pipeline_prepend)}")
            if doc.pipeline_append:
                lines.append(f"  append: {json.dumps(doc.pipeline_append)}")
            if doc.pipeline_skip:
                lines.append(f"  skip: {json.dumps(doc.pipeline_skip)}")
        lines.append(f"target_confidence: {doc.target_confidence}")
        lines.append(f"max_iterations: {doc.max_iterations}")
        lines.append(f"timeout_s: {doc.timeout_s}")
        lines.append(f"allow_self_improvement: {json.dumps(doc.allow_self_improvement)}")
        lines.append(f"require_metacognitive: {json.dumps(doc.require_metacognitive)}")
        lines.append(f"kill_on_diverge: {json.dumps(doc.kill_on_diverge)}")

        warnings = doc._raw_frontmatter.get("_warnings", [])
        if warnings:
            lines.append(f"# validation_warnings: {len(warnings)}")

        lines.append("---")
        return "\n".join(lines)
