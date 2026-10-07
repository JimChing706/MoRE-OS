"""R-08 回归测试：best-of-k 并行化（并发度 / 耗时 / 深拷贝 / 回退 / 选择语义）。"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from more_core.layers.l0_execution import ExecutionLayer
from more_core.llm.provider import LLMRequest, LLMResponse
from more_core.tools.registry import ToolResult

CODE_BLOCK = "```python\nx = 1\n```"


class _SlowLLM:
    """可控延迟的假 LLM，用于观测并发度与请求对象身份。"""

    def __init__(self, delay: float = 0.2, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.active = 0
        self.max_concurrent = 0
        self.requests: list[LLMRequest] = []

    async def generate(self, req, provider=None, model_override=None, **kw):  # noqa: ANN001
        self.active += 1
        self.max_concurrent = max(self.max_concurrent, self.active)
        self.requests.append(req)
        try:
            await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("candidate generation failed")
            return LLMResponse(
                content=CODE_BLOCK,
                provider="fake",
                model="fake-1",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=self.delay * 1000,
            )
        finally:
            self.active -= 1


class _Tools:
    def __init__(self, success: bool = True, output: str = "ok") -> None:
        self.success = success
        self.output = output
        self.calls = 0

    async def invoke(self, name, params, user_id="anonymous"):  # noqa: ANN001
        self.calls += 1
        return ToolResult(tool=name, success=self.success, output=self.output)


def _ctx(llm, tools, *, parallel: bool = True):
    return SimpleNamespace(
        core=SimpleNamespace(llm=llm, tools=tools),
        request=SimpleNamespace(context={"candidates_parallel": parallel}),
        scratch={},
        user_id="tester",
    )


def _req() -> LLMRequest:
    return LLMRequest(prompt="写一个函数", system=None, temperature=0.6, max_tokens=256)


# ---------------------------------------------------------------------------
# 并发度与耗时
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_candidates_overlap():
    llm = _SlowLLM(delay=0.25)
    ctx = _ctx(llm, _Tools(), parallel=True)
    layer = ExecutionLayer()

    t0 = time.perf_counter()
    _cand, tok_in, tok_out = await layer._select_best_candidate(
        ctx, _req(), None, None, assertions=None, k=2
    )
    elapsed = time.perf_counter() - t0
    assert llm.max_concurrent == 2, f"未并发，max_concurrent={llm.max_concurrent}"
    assert elapsed < 0.45, f"并行未生效，耗时 {elapsed:.2f}s"
    assert tok_in == 20 and tok_out == 10


@pytest.mark.asyncio
async def test_serial_mode_when_disabled():
    llm = _SlowLLM(delay=0.15)
    ctx = _ctx(llm, _Tools(), parallel=False)
    layer = ExecutionLayer()

    t0 = time.perf_counter()
    await layer._select_best_candidate(ctx, _req(), None, None, assertions=None, k=2)
    elapsed = time.perf_counter() - t0
    assert llm.max_concurrent == 1
    assert elapsed >= 0.28, f"串行对照应更慢，实际 {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_parallel_faster_than_serial():
    layer = ExecutionLayer()
    llm_p = _SlowLLM(delay=0.2)
    t0 = time.perf_counter()
    await layer._select_best_candidate(
        _ctx(llm_p, _Tools(), parallel=True), _req(), None, None, assertions=None, k=2
    )
    parallel_s = time.perf_counter() - t0

    llm_s = _SlowLLM(delay=0.2)
    t0 = time.perf_counter()
    await layer._select_best_candidate(
        _ctx(llm_s, _Tools(), parallel=False), _req(), None, None, assertions=None, k=2
    )
    serial_s = time.perf_counter() - t0

    assert parallel_s < serial_s * 0.8, f"parallel={parallel_s:.2f}s serial={serial_s:.2f}s"


@pytest.mark.asyncio
async def test_default_is_serial_when_flag_absent():
    """默认必须串行：3+3 轮实测本地单实例后端并发无收益（中位 7.0s vs 7.0s）。"""
    llm = _SlowLLM(delay=0.12)
    ctx = _ctx(llm, _Tools())
    ctx.request.context = {"candidates": 2}  # 不设置 candidates_parallel
    await ExecutionLayer()._select_best_candidate(ctx, _req(), None, None, assertions=None, k=2)
    assert llm.max_concurrent == 1, "默认应为串行"


@pytest.mark.asyncio
async def test_explicit_flag_enables_parallel():
    llm = _SlowLLM(delay=0.12)
    ctx = _ctx(llm, _Tools(), parallel=True)
    await ExecutionLayer()._select_best_candidate(ctx, _req(), None, None, assertions=None, k=2)
    assert llm.max_concurrent == 2, "显式开启后应并发"


# ---------------------------------------------------------------------------
# 请求隔离（深拷贝）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_candidate_gets_independent_request():
    llm = _SlowLLM(delay=0.05)
    ctx = _ctx(llm, _Tools(), parallel=True)
    layer = ExecutionLayer()
    original = _req()

    await layer._select_best_candidate(ctx, original, None, None, assertions=None, k=3)

    assert len(llm.requests) == 3
    ids = {id(r) for r in llm.requests}
    assert len(ids) == 3, "候选共享了同一个请求对象（存在数据竞争）"
    # 原始请求不被就地修改
    assert original.temperature == 0.6
    # 刻意不做参数扰动：并行与串行的候选分布必须一致（否则结果不可比，
    # 且人为分歧会触发 differential + 额外修复轮次，实测多耗 36% token）
    temps = {r.temperature for r in llm.requests}
    assert temps == {0.6}, f"并行路径不应扰动候选参数：{temps}"


@pytest.mark.asyncio
async def test_k_equals_one_skips_parallel_helpers():
    llm = _SlowLLM(delay=0.05)
    ctx = _ctx(llm, _Tools(), parallel=True)
    await ExecutionLayer()._select_best_candidate(ctx, _req(), None, None, assertions=None, k=1)
    assert len(llm.requests) == 1


# ---------------------------------------------------------------------------
# 回退与选择语义
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_falls_back_to_serial_when_all_parallel_fail():
    """并行分支整体失败 → 回退串行（保持原有可用性）。"""
    failing = _SlowLLM(delay=0.02, fail=True)
    ctx = _ctx(failing, _Tools(), parallel=True)

    layer = ExecutionLayer()
    call_count = {"n": 0}
    real_do_generate = layer._do_generate

    async def _flaky(ctx_, req, provider, model):
        call_count["n"] += 1
        if call_count["n"] <= 2:  # 前两次（并行路）失败
            raise RuntimeError("boom")
        return await real_do_generate(ctx_, req, provider, model)

    layer._do_generate = _flaky  # type: ignore[assignment]
    # 串行回退时用不失败的 LLM
    ctx.core.llm = _SlowLLM(delay=0.02)
    cand, _i, _o = await layer._select_best_candidate(ctx, _req(), None, None, assertions=None, k=2)
    assert cand.sbx is not None and cand.sbx.success, "回退后仍未产出可用候选"


@pytest.mark.asyncio
async def test_differential_disagreement_still_detected_in_parallel():
    """并行不得改变选择语义：候选输出不一致时必须标记 differential。"""

    class _DivergentLLM(_SlowLLM):
        async def generate(self, req, provider=None, model_override=None, **kw):  # noqa: ANN001
            self.active += 1
            self.max_concurrent = max(self.max_concurrent, self.active)
            self.requests.append(req)
            try:
                await asyncio.sleep(self.delay)
                n = len(self.requests)
                return LLMResponse(
                    content=f"```python\nprint({n})\n```",
                    provider="fake",
                    model="m",
                    prompt_tokens=1,
                    completion_tokens=1,
                    latency_ms=1.0,
                )
            finally:
                self.active -= 1

    # 让每个候选的沙箱输出不同，触发 differential
    outputs = iter(["a", "b", "c"])

    class _OutTools:
        async def invoke(self, name, params, user_id="anonymous"):  # noqa: ANN001
            return ToolResult(tool=name, success=True, output=next(outputs, "z"))

    ctx = _ctx(_DivergentLLM(delay=0.05), _OutTools(), parallel=True)
    cand, _i, _o = await ExecutionLayer()._select_best_candidate(
        ctx, _req(), None, None, assertions=None, k=3
    )
    assert cand.differential is True
    assert cand.ok is False
