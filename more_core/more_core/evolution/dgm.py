"""Darwin-Gödel Machine (DGM) controlled evolution engine.

Full evolution cycle: propose → evaluate → verify/reject → archive.
Benchmarks (SWE-bench, Polyglot, custom) are plugged via
:class:`BenchmarkRunner`.  Variants that score above the improvement
threshold are marked *verified*; all others remain unverified.

Includes LLM-based variant generation for actual self-improvement.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ..core.types import TaskRequest
from ..llm.provider import LLMRequest
from .archive import EvolutionArchive, EvolvedAgent
from .benchmark import BenchmarkReport, BenchmarkRunner

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime.orchestrator import MoRECore

_log = logging.getLogger(__name__)

# A variant must score at least this much above its parent to be verified.
_IMPROVEMENT_THRESHOLD = 0.02

_VARIANT_CODE_RE = re.compile(r"<variant_code>\s*(.*?)\s*</variant_code>", re.DOTALL)


class DGMEngine:
    def __init__(self, archive: EvolutionArchive) -> None:
        self.archive = archive
        self._runner: BenchmarkRunner | None = None
        self._core: MoRECore | None = None

    def set_runner(self, runner: BenchmarkRunner) -> None:
        self._runner = runner

    def set_core(self, core: MoRECore) -> None:
        self._core = core

    # -- snapshot ----------------------------------------------------------

    async def snapshot(self, branch: str = "main") -> EvolvedAgent:
        best = self.archive.best(branch)
        if best is not None:
            return best
        seed = EvolvedAgent(
            id=self.archive.new_id(branch),
            parent_id=None,
            generation=0,
            branch=branch,
            code=self._default_seed_code(),
            performance=0.2,
            description="initial seed",
        )
        self.archive.add(seed)
        return seed

    @staticmethod
    def _default_seed_code() -> str:
        return '''"""MoRE Agent - Self-Evolving Agent System."""

from typing import Any

class AgentConfig:
    max_retries: int = 3
    timeout: float = 30.0
    temperature: float = 0.7

async def execute_task(query: str, context: dict[str, Any]) -> str:
    """Execute a task with the given query and context."""
    return f"Processed: {query}"

CONFIG = AgentConfig()
'''

    # -- LLM-based proposal ----------------------------------------------------------

    async def propose_variant_llm(self, parent: EvolvedAgent, request: TaskRequest) -> EvolvedAgent:
        """Use LLM to propose an improved variant of the parent agent."""
        if self._core is None:
            _log.warning("No core configured; falling back to basic variant")
            return await self.propose_variant(parent, request)

        prompt = self._build_variant_prompt(parent, request)
        llm_req = LLMRequest(
            prompt=prompt,
            system="You are a DGM evolution engine. Generate improved agent code.",
            temperature=0.8,
            max_tokens=2048,
        )

        try:
            resp = await self._core.llm.generate(llm_req)
            code = self._extract_variant_code(resp.content)

            if not code:
                _log.warning("LLM did not return valid variant code; using basic")
                return await self.propose_variant(parent, request)

            variant = EvolvedAgent(
                id=self.archive.new_id(parent.branch),
                parent_id=parent.id,
                generation=parent.generation + 1,
                branch=parent.branch,
                code=code,
                performance=parent.performance,
                description=f"LLM-generated variant of {parent.id}",
                verified=False,
            )
            self.archive.add(variant)
            _log.info("Created LLM variant %s from parent %s", variant.id, parent.id)
            return variant

        except Exception as e:  # noqa: BLE001
            _log.error("LLM variant generation failed: %s; using basic", e)
            return await self.propose_variant(parent, request)

    def _build_variant_prompt(self, parent: EvolvedAgent, request: TaskRequest) -> str:
        return f"""Analyze the following parent agent code and generate an improved version.

Parent Agent (generation {parent.generation}):
```python
{parent.code}
```

Task Context: {request.query}

Current Performance: {parent.performance:.3f}

Generate improved agent code that addresses the task. Focus on:
1. Better error handling
2. More efficient algorithms
3. Enhanced capabilities
4. Improved robustness

Output the improved code in <variant_code> tags:
<variant_code>
# Your improved code here
</variant_code>"""

    def _extract_variant_code(self, content: str) -> str | None:
        match = _VARIANT_CODE_RE.search(content)
        if match:
            return match.group(1).strip()
        if "```python" in content:
            code_block = content.split("```python")[1].split("```", maxsplit=1)[0]
            return code_block.strip()
        return None

    # -- basic proposal ----------------------------------------------------------

    async def propose_variant(self, parent: EvolvedAgent, request: TaskRequest) -> EvolvedAgent:
        variant = EvolvedAgent(
            id=self.archive.new_id(parent.branch),
            parent_id=parent.id,
            generation=parent.generation + 1,
            branch=parent.branch,
            code=self._evolve_code(parent.code, request),
            performance=parent.performance,
            description=f"variant of {parent.id} (unverified)",
            verified=False,
        )
        self.archive.add(variant)
        return variant

    def _evolve_code(self, parent_code: str, request: TaskRequest) -> str:
        """Basic code evolution: add task-specific enhancements."""
        enhancements = [
            f"# Task: {request.type.value}",
            f"# Generated for: {request.id[:12]}",
            "",
            parent_code,
            "",
            "# --- Evolution Enhancement ---",
            "async def enhanced_execute(query: str, context: dict) -> str:",
            "    try:",
            "        return await execute_task(query, context)",
            "    except Exception as e:",
            '        return f"Error: {{e}}"',
        ]
        return "\n".join(enhancements)

    # -- evaluation loop ---------------------------------------------------

    async def evaluate_variant(
        self,
        variant: EvolvedAgent,
        benchmark_name: str = "simple",
    ) -> BenchmarkReport | None:
        """Run *variant* through a benchmark and update archive accordingly."""
        if self._runner is None:
            _log.warning("no benchmark runner configured; skipping evaluation")
            return None
        report = await self._runner.run(variant, benchmark_name)
        variant.performance = report.score
        if report.score >= (self._parent_score(variant) + _IMPROVEMENT_THRESHOLD):
            variant.verified = True
            variant.description = (
                f"verified (score={report.score:.3f}, pass_rate={report.pass_rate:.1%})"
            )
            _log.info("variant %s VERIFIED score=%.3f", variant.id, report.score)
        else:
            variant.description = f"rejected (score={report.score:.3f} < threshold)"
            _log.info("variant %s REJECTED score=%.3f", variant.id, report.score)
        # Persist updated fields back to archive
        self.archive.update(variant)
        return report

    # -- full cycle --------------------------------------------------------

    async def evolve(
        self,
        request: TaskRequest,
        branch: str = "main",
        benchmark_name: str = "simple",
    ) -> tuple[EvolvedAgent, BenchmarkReport | None]:
        """Full DGM cycle: snapshot → propose → evaluate → archive."""
        parent = await self.snapshot(branch)
        variant = await self.propose_variant(parent, request)
        report = await self.evaluate_variant(variant, benchmark_name)
        return variant, report

    # -- helpers -----------------------------------------------------------

    def _parent_score(self, agent: EvolvedAgent) -> float:
        if agent.parent_id is None:
            return 0.0
        parent = self.archive.get(agent.parent_id)
        return parent.performance if parent else 0.0
