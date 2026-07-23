"""Benchmark harness for DGM evaluation loop.

Provides a pluggable :class:`BenchmarkRunner` that evaluates agent variants
against test suites (SWE-bench style, Polyglot, custom).  Results feed back
into the evolution archive to mark variants as verified or rejected.

Production benchmarks register via the plugin system; this module ships a
minimal ``SimpleBenchmark`` for unit-testing and local dev.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .archive import EvolvedAgent

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime.orchestrator import MoRECore


@dataclass(slots=True)
class BenchmarkCase:
    """Single test case in a benchmark suite."""

    id: str
    input: str
    expected: str
    tags: list[str] = field(default_factory=list)
    timeout_s: float = 30.0


@dataclass(slots=True)
class CaseResult:
    case_id: str
    passed: bool
    actual: str = ""
    score: float = 0.0
    duration_ms: float = 0.0
    error: str = ""


@dataclass(slots=True)
class BenchmarkReport:
    benchmark_name: str
    agent_id: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    score: float = 0.0
    duration_ms: float = 0.0
    case_results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


class Benchmark(ABC):
    """Abstract benchmark suite."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def cases(self) -> list[BenchmarkCase]: ...

    @abstractmethod
    async def evaluate(self, case: BenchmarkCase, agent_output: str) -> CaseResult: ...


class SimpleBenchmark(Benchmark):
    """Minimal string-match benchmark for dev/testing."""

    def __init__(self, suite: list[BenchmarkCase] | None = None) -> None:
        self._cases = suite or []

    @property
    def name(self) -> str:
        return "simple"

    def cases(self) -> list[BenchmarkCase]:
        return list(self._cases)

    async def evaluate(self, case: BenchmarkCase, agent_output: str) -> CaseResult:
        passed = case.expected.strip() in agent_output.strip()
        return CaseResult(
            case_id=case.id,
            passed=passed,
            actual=agent_output[:500],
            score=1.0 if passed else 0.0,
        )


class BenchmarkRunner:
    """Runs an :class:`EvolvedAgent` through a suite and returns a report."""

    def __init__(self, core: "MoRECore") -> None:
        self._core = core
        self._benchmarks: dict[str, Benchmark] = {}

    def register(self, benchmark: Benchmark) -> None:
        self._benchmarks[benchmark.name] = benchmark

    def list(self) -> list[str]:
        return list(self._benchmarks.keys())

    async def run(
        self,
        agent: EvolvedAgent,
        benchmark_name: str,
        *,
        concurrency: int = 4,
    ) -> BenchmarkReport:
        bm = self._benchmarks.get(benchmark_name)
        if bm is None:
            return BenchmarkReport(
                benchmark_name=benchmark_name,
                agent_id=agent.id,
            )

        cases = bm.cases()
        start = time.perf_counter()
        results: list[CaseResult] = []

        sem = asyncio.Semaphore(concurrency)

        async def _eval_one(case: BenchmarkCase) -> CaseResult:
            async with sem:
                from ..core.types import TaskRequest

                t0 = time.perf_counter()
                try:
                    task = TaskRequest(query=case.input, timeout_s=case.timeout_s)
                    result = await self._core.execute(task)
                    cr = await bm.evaluate(case, result.output)
                    cr.duration_ms = (time.perf_counter() - t0) * 1000
                    return cr
                except Exception as exc:
                    return CaseResult(
                        case_id=case.id,
                        passed=False,
                        error=str(exc),
                        duration_ms=(time.perf_counter() - t0) * 1000,
                    )

        results = await asyncio.gather(*[_eval_one(c) for c in cases], return_exceptions=False)

        passed = sum(1 for r in results if r.passed)
        total_score = sum(r.score for r in results) / len(results) if results else 0.0
        return BenchmarkReport(
            benchmark_name=benchmark_name,
            agent_id=agent.id,
            total=len(cases),
            passed=passed,
            failed=len(cases) - passed,
            score=total_score,
            duration_ms=(time.perf_counter() - start) * 1000,
            case_results=list(results),
        )
