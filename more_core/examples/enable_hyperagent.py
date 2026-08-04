"""Example: Enable and run L5 HyperAgent self-modification.

Usage:
    export MORE_ENABLE_METACOGNITION=1
    python3 examples/enable_hyperagent.py
"""

import asyncio
import os
from dataclasses import dataclass

os.environ["MORE_ENABLE_METACOGNITION"] = "1"

from more_core import MoRECore, TaskRequest, TaskType
from more_core.governance import GovernanceWorkflow


@dataclass
class MockCore:
    settings: object
    event_bus: object


async def main():
    print("=== L5 HyperAgent Self-Modification Demo ===\n")

    core = await MoRECore.from_env()
    await core.start()

    print(f"Settings.enable_metacognition: {core.settings.enable_metacognition}\n")

    print("--- Submitting SELF_IMPROVEMENT task ---")
    request = TaskRequest(
        type=TaskType.SELF_IMPROVEMENT,
        query="Analyze the current routing pipeline and suggest improvements",
        allow_self_improvement=True,
        require_metacognitive_monitoring=True,
    )
    result = await core.execute(request)
    print(f"Result confidence: {result.output}\n")

    print("--- Proposals from MetacognitionService ---")
    proposals = core.metacognition.get_proposals()
    for p in proposals:
        print(f"  {p.id}: {p.target} ({p.status}) - {p.rationale}")

    print("\n--- Governance Workflow ---")
    workflow = GovernanceWorkflow(core.settings)
    for p in proposals:
        workflow.submit_proposal(
            p.id,
            {"target": p.target, "content": p.content, "rationale": p.rationale},
        )

    print("\n--- Applying Approved Proposals (dry-run) ---")
    results = await core.metacognition.apply_approved_proposals(dry_run=True)
    for proposal_id, success, msg in results:
        print(f"  {proposal_id}: {'Success' if success else 'Failed'} - {msg}")

    await core.stop()
    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())