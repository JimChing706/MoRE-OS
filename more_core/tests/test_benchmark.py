"""Tests for DGM benchmark and evaluation loop."""

import pytest

from more_core.evolution.archive import EvolutionArchive, EvolvedAgent
from more_core.evolution.benchmark import (
    BenchmarkCase,
    BenchmarkRunner,
    DEFAULT_SUITE,
    SimpleBenchmark,
)
from more_core.evolution.dgm import DGMEngine
from more_core.core.types import TaskRequest


@pytest.fixture
def archive():
    return EvolutionArchive()


@pytest.fixture
def dgm(archive):
    return DGMEngine(archive)


@pytest.mark.asyncio
async def test_simple_benchmark_pass():
    bm = SimpleBenchmark(
        [
            BenchmarkCase(id="c1", input="hello", expected="hello"),
        ]
    )
    result = await bm.evaluate(bm.cases()[0], "hello world")
    assert result.passed
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_simple_benchmark_fail():
    bm = SimpleBenchmark(
        [
            BenchmarkCase(id="c1", input="hello", expected="xyz"),
        ]
    )
    result = await bm.evaluate(bm.cases()[0], "hello world")
    assert not result.passed
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_dgm_snapshot_creates_seed(dgm):
    seed = await dgm.snapshot("test")
    assert seed.generation == 0
    assert seed.parent_id is None


@pytest.mark.asyncio
async def test_dgm_propose_variant(dgm):
    seed = await dgm.snapshot("test")
    variant = await dgm.propose_variant(seed, TaskRequest(query="test"))
    assert variant.parent_id == seed.id
    assert variant.generation == 1
    assert not variant.verified


@pytest.mark.asyncio
async def test_dgm_evaluate_without_runner(dgm):
    seed = await dgm.snapshot("test")
    variant = await dgm.propose_variant(seed, TaskRequest(query="test"))
    report = await dgm.evaluate_variant(variant)
    assert report is None


@pytest.mark.asyncio
async def test_benchmark_runner(core):
    bm = SimpleBenchmark(
        [
            BenchmarkCase(id="c1", input="hello", expected="fake-reply"),
        ]
    )
    runner = BenchmarkRunner(core)
    runner.register(bm)
    seed = EvolvedAgent(
        id="test_agent",
        parent_id=None,
        generation=0,
        branch="test",
        code="",
        performance=0.0,
    )
    report = await runner.run(seed, "simple")
    assert report.total == 1
    assert report.benchmark_name == "simple"


def test_default_suite_is_seeded():
    """SimpleBenchmark() without a suite falls back to DEFAULT_SUITE.

    This keeps the DGM/L2 evaluation loop from always rejecting variants
    when no benchmark plugin is registered.
    """
    bm = SimpleBenchmark()
    cases = bm.cases()
    assert len(cases) == len(DEFAULT_SUITE) == 3
    assert {c.id for c in cases} == {"code_fib", "code_sort", "code_hello"}
    assert all(c.expected for c in cases)


@pytest.mark.asyncio
async def test_default_suite_evaluates_code_fib():
    """A competent code-gen output should satisfy the seeded suite."""
    from more_core.evolution.benchmark import DEFAULT_SUITE

    bm = SimpleBenchmark()
    fib_case = next(c for c in DEFAULT_SUITE if c.id == "code_fib")
    result = await bm.evaluate(
        fib_case,
        "```python\ndef fib(n: int) -> int:\n    ...\n```",
    )
    assert result.passed
    assert result.score == 1.0
