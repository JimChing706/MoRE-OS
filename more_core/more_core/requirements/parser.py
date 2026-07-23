"""Markdown Requirements Parser - Parse requirements documents and create tasks."""

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime
from enum import Enum


class Priority(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RequirementType(Enum):
    FEATURE = "feature"
    BUG = "bug"
    IMPROVEMENT = "improvement"
    TASK = "task"
    STORY = "story"


@dataclass
class RequirementItem:
    """Single requirement item parsed from markdown."""

    id: str
    title: str
    description: str = ""
    priority: str = "medium"
    type: str = "feature"
    acceptance_criteria: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    estimated_hours: float = 0.0
    labels: list[str] = field(default_factory=list)
    status: str = "pending"
    assignee: str = ""
    parent_id: Optional[str] = None
    story_points: Optional[int] = None


@dataclass
class RequirementsDocument:
    """Parsed requirements document."""

    title: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    created_at: str = ""
    items: list[RequirementItem] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    project: str = ""


class RequirementsParser:
    """Parse Markdown requirements documents into structured data."""

    def __init__(self) -> None:
        self._priority_keywords = {
            "high": ["高", "high", "重要", "critical", "must", "必须", "P0", "P1"],
            "medium": ["中", "medium", "普通", "should", "应该", "P2", "P3"],
            "low": ["低", "low", " minor", "可选", "nice", "P4"],
        }
        self._type_keywords = {
            "feature": ["功能", "feature", "功能点", "需求", "story"],
            "bug": ["bug", "缺陷", "修复", "问题", "错误"],
            "improvement": ["改进", "优化", "improvement", "提升", "enhancement"],
            "task": ["任务", "task", "工作", "todo"],
        }
        self._status_keywords = {
            "done": ["完成", "done", "已完成", "closed", "完成"],
            "in_progress": ["进行中", "in progress", "处理中", "active"],
            "pending": ["待处理", "pending", "未开始", "todo", "计划"],
        }

    def parse(self, markdown_content: str) -> RequirementsDocument:
        """Parse markdown content into RequirementsDocument."""
        lines = markdown_content.split("\n")
        doc = RequirementsDocument()
        doc.created_at = datetime.now().isoformat()

        current_item: Optional[RequirementItem] = None
        in_acceptance_criteria = False
        in_dependencies = False

        for line in lines:
            line = line.strip()

            if not line:
                if current_item and in_acceptance_criteria:
                    in_acceptance_criteria = False
                continue

            if line.startswith("# "):
                doc.title = line[2:].strip()
            elif line.startswith("## "):
                section = line[3:].strip().lower()
                if "描述" in section or "description" in section:
                    pass
                elif "元数据" in section or "metadata" in section:
                    pass
                elif "项目" in section or "project" in section:
                    pass
            elif line.startswith("**") and "**" in line[2:]:
                key_value = line.replace("**", "").split(":")
                if len(key_value) == 2:
                    key = key_value[0].strip().lower()
                    value = key_value[1].strip()
                    if "版本" in key or "version" in key:
                        doc.version = value
                    elif "作者" in key or "author" in key:
                        doc.author = value
                    elif "项目" in key or "project" in key:
                        doc.project = value
                    else:
                        doc.metadata[key] = value
            elif (
                re.match(r"^[-*]\s+\[[ xX]\]\s+", line)
                or re.match(r"^[-*]\s+\d+[\.\)]\s+", line)
                or re.match(r"^\s*▏\s+", line)
            ):
                if current_item:
                    doc.items.append(current_item)

                # Try different patterns
                match = re.match(r"^[-*]\s+\[[ xX]\]\s+(.+)", line)
                if match:
                    title = match.group(1).strip()
                else:
                    match = re.match(r"^[-*]\s+\d+[\.\)]\s+(.+)", line)
                    if match:
                        title = match.group(1).strip()
                    else:
                        # Support ▏ character
                        match = re.match(r"^\s*▏\s+(.+)", line)
                        title = match.group(1).strip() if match else line.strip()

                item_id = f"REQ-{len(doc.items) + 1:03d}"
                current_item = RequirementItem(
                    id=item_id,
                    title=title,
                    description=title,
                    priority=self._detect_priority(title),
                    type=self._detect_type(title),
                )
                in_acceptance_criteria = False
                in_dependencies = False

            elif line.startswith("## ") and "标签" in line:
                pass

            elif line.startswith("- ") and not line.startswith("- ["):
                if current_item and not in_acceptance_criteria and not in_dependencies:
                    current_item.labels.append(line[2:].strip())

            elif current_item:
                if line.startswith("### "):
                    section = line[4:].strip().lower()
                    if "验收" in section or "acceptance" in section or "标准" in section:
                        in_acceptance_criteria = True
                        in_dependencies = False
                    elif "依赖" in section or "dependency" in section:
                        in_dependencies = True
                        in_acceptance_criteria = False
                    else:
                        in_acceptance_criteria = False
                        in_dependencies = False

                elif in_acceptance_criteria and (
                    line.startswith("-") or line.startswith("*") or line.startswith("+")
                ):
                    criteria = line.lstrip("-*+ ").strip()
                    if criteria and not criteria.startswith("["):
                        current_item.acceptance_criteria.append(criteria)

                elif in_dependencies and (
                    line.startswith("-") or line.startswith("*") or line.startswith("+")
                ):
                    dep = line.lstrip("-*+ ").strip()
                    if dep:
                        current_item.dependencies.append(dep)

                elif line.startswith("|") and "---" not in line:
                    pass

                elif not line.startswith("#") and not line.startswith("!"):
                    if not current_item.description:
                        current_item.description = line
                    else:
                        current_item.description += " " + line

                priority_match = re.search(
                    r"(优先级|priority)[:\s]+(高|中|低|high|medium|low|P\d)", line, re.IGNORECASE
                )
                if priority_match:
                    current_item.priority = self._detect_priority(priority_match.group(2))

                hours_match = re.search(
                    r"(预计|estimated|时间|工时)[:\s]+(\d+\.?\d*)\s*(小时|h|hours)?",
                    line,
                    re.IGNORECASE,
                )
                if hours_match:
                    try:
                        current_item.estimated_hours = float(hours_match.group(2))
                    except ValueError:
                        pass

                status_match = re.search(
                    r"(状态|status)[:\s]+(完成|进行中|待处理|done|in progress|pending)",
                    line,
                    re.IGNORECASE,
                )
                if status_match:
                    current_item.status = self._detect_status(status_match.group(2))

                assignee_match = re.search(r"(负责人|assignee)[:\s]+(\S+)", line, re.IGNORECASE)
                if assignee_match:
                    current_item.assignee = assignee_match.group(2)

                points_match = re.search(
                    r"(故事点|story points|points)[:\s]+(\d+)", line, re.IGNORECASE
                )
                if points_match:
                    try:
                        current_item.story_points = int(points_match.group(2))
                    except ValueError:
                        pass

        if current_item:
            doc.items.append(current_item)

        return doc

    def _detect_priority(self, text: str) -> str:
        """Detect priority from text."""
        text_lower = text.lower()
        for priority, keywords in self._priority_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    return priority
        return "medium"

    def _detect_type(self, text: str) -> str:
        """Detect requirement type from text."""
        text_lower = text.lower()
        for req_type, keywords in self._type_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    return req_type
        return "feature"

    def _detect_status(self, text: str) -> str:
        """Detect status from text."""
        text_lower = text.lower()
        for status, keywords in self._status_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    return status
        return "pending"

    def to_tasks(self, doc: RequirementsDocument) -> list[dict[str, Any]]:
        """Convert requirements to task list for MoRE OS."""
        tasks = []
        for item in doc.items:
            task = {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "type": "nlp_task",
                "priority": item.priority,
                "requirements_type": item.type,
                "status": item.status,
                "acceptance_criteria": item.acceptance_criteria,
                "estimated_hours": item.estimated_hours,
                "story_points": item.story_points,
                "labels": item.labels,
                "dependencies": item.dependencies,
                "assignee": item.assignee,
                "parent_id": item.parent_id,
                "context": {
                    "document_title": doc.title,
                    "document_version": doc.version,
                    "document_author": doc.author,
                    "document_project": doc.project,
                    "requirement_id": item.id,
                    "created_at": doc.created_at,
                },
            }
            tasks.append(task)
        return tasks


def parse_requirements(markdown: str) -> RequirementsDocument:
    """Parse markdown requirements document."""
    parser = RequirementsParser()
    return parser.parse(markdown)


def requirements_to_tasks(markdown: str) -> list[dict[str, Any]]:
    """Parse markdown and convert to task list."""
    doc = parse_requirements(markdown)
    parser = RequirementsParser()
    return parser.to_tasks(doc)
