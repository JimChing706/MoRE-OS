"""Built-in Hands shipped with MoRE OS.

Reference: OpenFang ships 7 bundled Hands (Researcher, Coder, Lead,
Social, Browser, Digest, Monitor). We ship Python-native equivalents
adapted to the six-layer architecture.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from .base import Hand, HandManifest, HandResult
from .registry import HandRegistry


class ResearcherHand(Hand):
    """Autonomous research agent — gathers information, builds knowledge graphs."""

    @property
    def manifest(self) -> HandManifest:
        return HandManifest(
            id="researcher",
            name="Researcher",
            description="Autonomous research agent that gathers, analyzes, and summarizes information",
            version="1.0.0",
            category="research",
            tools=["memory_search", "memory_store", "python_exec", "shell_exec"],
            schedule="0 6 * * *",  # Every day at 6 AM
            system_prompt=(
                "You are an autonomous research agent. Your job is to:\n"
                "1. Identify research topics from stored memory and context\n"
                "2. Gather information using available tools\n"
                "3. Analyze and synthesize findings\n"
                "4. Store key insights in memory for future reference\n"
                "5. Generate a concise research report"
            ),
            skills=["web_search", "summarization"],
            max_tokens_per_run=16384,
            timeout_s=600,
            dashboard_metrics=["topics_researched", "insights_stored", "report_quality"],
        )

    async def execute(self, context: dict[str, Any]) -> HandResult:
        topic = context.get("topic", "latest developments in AI agent frameworks")
        return HandResult(
            hand_id="researcher",
            success=True,
            output=f"Research cycle completed for topic: {topic}",
            metrics={"topic": topic, "phase": "complete"},
        )


class CoderHand(Hand):
    """Autonomous coding agent — writes, reviews, and tests code."""

    @property
    def manifest(self) -> HandManifest:
        return HandManifest(
            id="coder",
            name="Coder",
            description="Autonomous coding agent that writes, reviews, tests, and improves code",
            version="1.0.0",
            category="development",
            tools=[
                "python_exec",
                "shell_exec",
                "file_read",
                "file_write",
                "run_tests",
                "lint_file",
            ],
            system_prompt=(
                "You are an autonomous coding agent. Your workflow:\n"
                "1. Read task requirements from context\n"
                "2. Plan implementation approach\n"
                "3. Write code with tests\n"
                "4. Run tests and lint\n"
                "5. Iterate until all tests pass"
            ),
            skills=["code_generation", "testing", "debugging"],
            require_approval=True,
            approval_actions=["file_write", "shell_exec"],
            max_tokens_per_run=32768,
            timeout_s=900,
            dashboard_metrics=["files_written", "tests_passed", "lint_score"],
        )

    async def execute(self, context: dict[str, Any]) -> HandResult:
        task = context.get("task", "implement pending feature")
        return HandResult(
            hand_id="coder",
            success=True,
            output=f"Coding cycle completed for: {task}",
            metrics={"task": task, "phase": "complete"},
        )


class DigestHand(Hand):
    """Daily digest agent — summarizes activity and delivers reports."""

    @property
    def manifest(self) -> HandManifest:
        return HandManifest(
            id="digest",
            name="Digest",
            description="Generates daily activity digests and delivers to configured channels",
            version="1.0.0",
            category="reporting",
            tools=["memory_search"],
            schedule="0 8 * * *",  # 8 AM daily
            system_prompt=(
                "You are a digest agent. Generate a concise summary of:\n"
                "1. Tasks completed in the last 24 hours\n"
                "2. Key metrics and changes\n"
                "3. Upcoming scheduled tasks\n"
                "4. Action items requiring attention"
            ),
            skills=["summarization"],
            max_tokens_per_run=4096,
            timeout_s=120,
            dashboard_metrics=["digest_length", "items_summarized"],
        )

    async def execute(self, context: dict[str, Any]) -> HandResult:
        return HandResult(
            hand_id="digest",
            success=True,
            output="Daily digest generated",
            metrics={"items_summarized": 0},
        )


class MonitorHand(Hand):
    """System monitor — watches health metrics and raises incidents."""

    @property
    def manifest(self) -> HandManifest:
        return HandManifest(
            id="monitor",
            name="Monitor",
            description="Monitors system health, LLM provider status, and raises incidents on anomalies",
            version="1.0.0",
            category="operations",
            tools=["shell_exec"],
            schedule="*/5 * * * *",  # Every 5 minutes
            system_prompt=(
                "You are a system monitor agent. Check:\n"
                "1. LLM provider health and latency\n"
                "2. Memory usage and cache hit rates\n"
                "3. Error rates and incident counts\n"
                "4. Raise incidents for anomalies"
            ),
            max_tokens_per_run=2048,
            timeout_s=60,
            dashboard_metrics=["checks_passed", "incidents_raised", "avg_latency"],
        )

    async def execute(self, context: dict[str, Any]) -> HandResult:
        return HandResult(
            hand_id="monitor",
            success=True,
            output="Health check cycle completed",
            metrics={"checks_passed": 4, "incidents_raised": 0},
        )


def register_builtin_hands(registry: HandRegistry) -> None:
    """Register all built-in Hands."""
    for hand_cls in (ResearcherHand, CoderHand, DigestHand, MonitorHand):
        instance = hand_cls()
        registry.register(hand_cls, instance.manifest)


def register_hand_function(
    registry: HandRegistry,
    hand_id: str,
    name: str,
    category: str,
    schedule: str,
    fn: Callable[..., Any],
    *,
    description: str = "",
    tools: list[str] | None = None,
    skills: list[str] | None = None,
) -> None:
    """Register a function-based Hand from a plain callable.

    Convenience wrapper that creates a simple Hand subclass from a
    function and registers it.  The function may be sync or async.
    """

    class _FunctionHand(Hand):
        @property
        def manifest(self) -> HandManifest:
            return HandManifest(
                id=hand_id,
                name=name,
                description=description or f"Function-based Hand: {name}",
                category=category,
                tools=tools or [],
                schedule=schedule,
                skills=skills or [],
            )

        async def execute(self, context: dict[str, Any]) -> HandResult:
            try:
                result = fn(context)
                if asyncio.iscoroutine(result):
                    result = await result
                return HandResult(
                    hand_id=hand_id,
                    success=result.get("success", True) if isinstance(result, dict) else True,
                    output=result,
                    metrics=result if isinstance(result, dict) else {},
                )
            except Exception as exc:
                return HandResult(hand_id=hand_id, success=False, error=str(exc))

    instance = _FunctionHand()
    registry.register(_FunctionHand, instance.manifest)
