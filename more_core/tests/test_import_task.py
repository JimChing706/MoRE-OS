"""Tests for the Import Task Document parser/generator."""

from __future__ import annotations

from more_core.core.import_task import (
    ImportTaskDocument,
    ImportTaskError,
    ImportTaskGenerator,
    ImportTaskParser,
    Priority,
    QualityGate,
    RequirementItem,
)


def _sample_itd_text() -> str:
    return """---
title: Test Task
version: 1.0.0
author: Test Author
created: 2026-07-22T10:00:00Z
type: code_generation
priority: high
deliverable_kind: code
tags: [test, unit]
estimated_hours: 4.0
pipeline:
  mode: standard
target_confidence: 80.0
max_iterations: 5
timeout_s: 120.0
---

# Executive Summary

A test task for unit testing.

# Requirements

## REQ-001: First Requirement
**Priority:** HIGH
**Description:** This is the first test requirement.

**Acceptance Criteria:**
- [ ] Criterion one
- [ ] Criterion two

## REQ-002: Second Requirement
**Priority:** MEDIUM
**Description:** This is the second test requirement.

**Acceptance Criteria:**
- [ ] Criterion three

# Deliverable Contract

**Kind:** code
**Required Dimensions:** core_output, reasoning, tests
**Minimum Output Length:** 100

**Quality Gates:**
| Gate | Threshold |
|------|-----------|
| min_output_length | 100 |
| must_contain_code_fence | true |

**Acceptance Criteria:**
- [ ] Unit tests pass with >80% coverage
- [ ] Integration test confirms behavior

# Kill Criteria

| ID | Condition | Severity | Timeline | Fallback |
|----|-----------|----------|----------|----------|
| KC-001 | Coverage drops below 70 | critical | immediate | Skip tests, file issue |

# Resource Budget

**Estimated Tokens:** 8,000
**Estimated Duration:** 20 minutes
**Max Iterations:** 5

# Context and Constraints

## Background
This is the background context.

## Constraints
- Constraint one
- Constraint two

## References
- ref one
- ref two

# Related Documents

- doc-001
- doc-002
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParser:
    def test_parse_basic(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())

        assert doc.title == "Test Task"
        assert doc.version == "1.0.0"
        assert doc.author == "Test Author"
        assert doc.type == "code_generation"
        assert doc.priority == "high"
        assert doc.deliverable_kind == "code"
        assert doc.tags == ["test", "unit"]
        assert doc.estimated_hours == 4.0
        assert doc.pipeline_mode == "standard"
        assert doc.target_confidence == 80.0
        assert doc.max_iterations == 5
        assert doc.timeout_s == 120.0
        assert doc.allow_self_improvement is False
        assert doc.require_metacognitive is False
        assert doc.kill_on_diverge is True

    def test_parse_summary(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())
        assert "A test task for unit testing" in doc.summary

    def test_parse_requirements(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())

        assert len(doc.requirements) == 2
        assert doc.requirements[0].id == "REQ-001"
        assert doc.requirements[0].title == "First Requirement"
        assert doc.requirements[0].priority == Priority.HIGH
        assert doc.requirements[0].acceptance_criteria == [
            "Criterion one",
            "Criterion two",
        ]

        assert doc.requirements[1].id == "REQ-002"
        assert doc.requirements[1].title == "Second Requirement"

    def test_parse_contract(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())

        assert doc.contract_kind == "code"
        assert doc.contract_required_dimensions == [
            "core_output", "reasoning", "tests",
        ]
        assert doc.contract_min_output_length == 100
        assert len(doc.contract_quality_gates) == 2
        assert doc.contract_quality_gates[0].name == "min_output_length"
        assert doc.contract_acceptance_criteria == [
            "Unit tests pass with >80% coverage",
            "Integration test confirms behavior",
        ]

    def test_parse_kill_criteria(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())

        assert len(doc.kill_criteria) == 1
        assert doc.kill_criteria[0].id == "KC-001"
        assert doc.kill_criteria[0].severity == "critical"
        assert doc.kill_criteria[0].timeline == "immediate"

    def test_parse_budget(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())

        assert doc.budget.estimated_tokens == 8000
        assert doc.budget.estimated_duration_min == 20
        assert doc.budget.max_iterations == 5

    def test_parse_context(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())

        assert "background context" in doc.context_background
        assert "Constraint one" in doc.context_constraints
        assert "Constraint two" in doc.context_constraints
        assert "ref one" in doc.context_references

    def test_parse_related_docs(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())

        assert doc.related_documents == ["doc-001", "doc-002"]

    def test_parse_no_frontmatter(self) -> None:
        parser = ImportTaskParser()
        try:
            parser.parse("# Executive Summary\n\nHello")
            assert False, "Expected ImportTaskError for missing title"
        except ImportTaskError:
            pass

    def test_parse_partial_minimal(self) -> None:
        text = """---
title: Minimal
version: 1.0.0
author: Me
created: 2026-01-01
type: nlp_task
priority: low
deliverable_kind: analysis
tags: [test]
---

# Executive Summary

Do something.
"""
        parser = ImportTaskParser()
        doc = parser.parse(text)
        assert doc.title == "Minimal"
        assert doc.type == "nlp_task"

    def test_validate_missing_title(self) -> None:
        text = """---
version: 1.0.0
author: Me
created: 2026-01-01
type: code_generation
priority: high
deliverable_kind: code
tags: [test]
---
"""
        parser = ImportTaskParser()
        try:
            parser.parse(text)
            assert False, "Expected ImportTaskError"
        except ImportTaskError as e:
            assert "R002" in str(e)

    def test_validate_bad_type(self) -> None:
        text = """---
title: Bad
version: 1.0.0
author: Me
created: 2026-01-01
type: invalid_type
priority: high
deliverable_kind: code
tags: [test]
---
"""
        parser = ImportTaskParser()
        try:
            parser.parse(text)
            assert False, "Expected ImportTaskError"
        except ImportTaskError as e:
            assert "R003" in str(e)


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------


class TestGenerator:
    def test_generate_roundtrip(self) -> None:
        parser = ImportTaskParser()
        generator = ImportTaskGenerator()

        doc1 = parser.parse(_sample_itd_text())
        markdown = generator.generate(doc1)
        doc2 = parser.parse(markdown)

        assert doc2.title == doc1.title
        assert doc2.type == doc1.type
        assert doc2.priority == doc1.priority
        assert len(doc2.requirements) == len(doc1.requirements)
        assert doc2.requirements[0].id == doc1.requirements[0].id
        assert (
            doc2.requirements[0].acceptance_criteria
            == doc1.requirements[0].acceptance_criteria
        )
        assert doc2.contract_kind == doc1.contract_kind
        assert (
            doc2.contract_required_dimensions
            == doc1.contract_required_dimensions
        )
        assert len(doc2.kill_criteria) == len(doc1.kill_criteria)
        assert doc2.budget.estimated_tokens == doc1.budget.estimated_tokens

    def test_generate_empty(self) -> None:
        generator = ImportTaskGenerator()
        doc = ImportTaskDocument(title="Empty Task")
        markdown = generator.generate(doc)
        assert "Empty Task" in markdown
        assert "# Executive Summary" in markdown
        assert "# Requirements" in markdown
        assert "# Deliverable Contract" in markdown

    def test_generate_frontmatter(self) -> None:
        generator = ImportTaskGenerator()
        doc = ImportTaskDocument(
            title="My Task",
            version="2.0.0",
            type="architecture_design",
            priority="high",
            tags=["arch", "design"],
        )
        markdown = generator.generate(doc)
        assert "title: My Task" in markdown
        assert "version: 2.0.0" in markdown
        assert "type: architecture_design" in markdown
        assert "tags:" in markdown


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())
        d = doc.to_dict()

        assert d["metadata"]["title"] == "Test Task"
        assert d["metadata"]["type"] == "code_generation"
        assert len(d["requirements"]) == 2
        assert d["requirements"][0]["id"] == "REQ-001"
        assert len(d["kill_criteria"]) == 1
        assert d["deliverable_contract"]["kind"] == "code"
        assert d["resource_budget"]["estimated_tokens"] == 8000
        assert "background context" in d["context"]["background"]
        assert d["related_documents"] == ["doc-001", "doc-002"]

    def test_to_task_request(self) -> None:
        parser = ImportTaskParser()
        doc = parser.parse(_sample_itd_text())
        req = doc.to_task_request()

        assert req.type.value == "code_generation"
        assert "A test task for unit testing" in req.query
        assert req.timeout_s == 120.0
        assert req.allow_self_improvement is False
        assert req.deliverable_kind == "code"
        assert req.expectation is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_text(self) -> None:
        parser = ImportTaskParser()
        try:
            parser.parse("")
            assert False, "Expected ImportTaskError for empty text"
        except ImportTaskError:
            pass

    def test_frontmatter_only(self) -> None:
        text = """---
title: Only Frontmatter
version: 1.0.0
author: Me
created: 2026-01-01
type: nlp_task
priority: low
deliverable_kind: analysis
tags: [test]
---
"""
        parser = ImportTaskParser()
        doc = parser.parse(text)
        assert doc.title == "Only Frontmatter"
        assert doc.summary == ""

    def test_pipeline_hints(self) -> None:
        text = """---
title: Pipeline Test
version: 1.0.0
author: Me
created: 2026-01-01
type: code_generation
priority: high
deliverable_kind: code
tags: [test]
pipeline:
  mode: deep
  prepend: ["L5"]
  append: ["L2"]
  skip: ["L3"]
---
"""
        parser = ImportTaskParser()
        doc = parser.parse(text)
        assert doc.pipeline_mode == "deep"
        assert doc.pipeline_prepend == ["L5"]
        assert doc.pipeline_append == ["L2"]
        assert doc.pipeline_skip == ["L3"]

    def test_plugin_type(self) -> None:
        text = """---
title: Plugin Task
version: 1.0.0
author: Me
created: 2026-01-01
type: plugin_defined
plugin_type: minesweeper
priority: medium
deliverable_kind: custom
tags: [plugin]
---
"""
        parser = ImportTaskParser()
        doc = parser.parse(text)
        assert doc.type == "plugin_defined"
        assert doc.plugin_type == "minesweeper"
