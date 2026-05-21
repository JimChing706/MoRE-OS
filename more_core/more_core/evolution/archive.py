"""Agent evolution archive (DGM lineage store).

In-memory baseline; production should persist to SQLite/Postgres.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass(slots=True)
class EvolvedAgent:
    id: str
    parent_id: str | None
    generation: int
    branch: str
    code: str
    performance: float = 0.0
    description: str = ""
    created_at: float = field(default_factory=time.time)
    verified: bool = False


class EvolutionArchive:
    def __init__(self, max_size: int = 500) -> None:
        self._agents: dict[str, EvolvedAgent] = {}
        self._by_branch: dict[str, list[str]] = {}
        self._max = max_size

    def add(self, agent: EvolvedAgent) -> None:
        if len(self._agents) >= self._max:
            # Evict the oldest *non-best* agent per branch.
            branch_agents = self._by_branch.get(agent.branch, [])
            best = self.best(agent.branch)
            best_id = best.id if best else None
            candidates = [aid for aid in branch_agents if aid != best_id]
            if candidates:
                oldest = min(candidates, key=lambda aid: self._agents[aid].created_at)
                self._agents.pop(oldest, None)
                branch_agents.remove(oldest)
        self._agents[agent.id] = agent
        self._by_branch.setdefault(agent.branch, []).append(agent.id)

    def get(self, agent_id: str) -> EvolvedAgent | None:
        return self._agents.get(agent_id)

    def branch(self, branch: str) -> list[EvolvedAgent]:
        return [self._agents[aid] for aid in self._by_branch.get(branch, [])]

    def best(self, branch: str | None = None) -> EvolvedAgent | None:
        pool = list(self._agents.values()) if branch is None else self.branch(branch)
        return max(pool, key=lambda a: a.performance) if pool else None

    def new_id(self, branch: str) -> str:
        gen = len(self._by_branch.get(branch, []))
        return f"{branch}_g{gen}_{uuid.uuid4().hex[:6]}"

    def update(self, agent: EvolvedAgent) -> None:
        """Update an existing agent's mutable fields in the archive."""
        if agent.id in self._agents:
            self._agents[agent.id] = agent

    def stats(self) -> dict[str, object]:
        return {
            "total_agents": len(self._agents),
            "branches": {b: len(v) for b, v in self._by_branch.items()},
            "best_score": self.best().performance if self._agents else 0.0,
        }
