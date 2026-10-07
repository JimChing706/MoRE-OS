#!/usr/bin/env python3
"""Validate the CS-FPS ITD through the platform's real ImportTaskParser.

Run from the platform repo:
    cd /Users/qnming/AI_Cample/QNMing_MoRE_OS_LIVE/more_core
    /Users/qnming/AI_Cample/QNMing_MoRE_OS_LIVE/.venv/bin/python \
        /Users/qnming/AI_Cample/QNMing_MoRE_OS_LIVE/deliverables/cs_fps/validate_itd.py
"""

import sys

from more_core.core.import_task import ImportTaskError, ImportTaskParser

ITD = "/Users/qnming/AI_Cample/QNMing_MoRE_OS_LIVE/deliverables/cs_fps/itd-cs-fps.md"


def main() -> int:
    md = open(ITD, encoding="utf-8").read()
    parser = ImportTaskParser()
    try:
        doc = parser.parse(md)
    except ImportTaskError as exc:
        print("PARSE FAILED:", exc)
        return 1

    print("=== ITD VALIDATION (platform ImportTaskParser) ===")
    print("title:", doc.title)
    print("type:", doc.type, "| priority:", doc.priority, "| kind:", doc.deliverable_kind)
    print("pipeline_mode:", doc.pipeline_mode)
    print("requirements:", [r.id for r in doc.requirements])
    print("acceptance_criteria:", len(doc.contract_acceptance_criteria))
    print("kill_criteria:", [k.id for k in doc.kill_criteria])
    print(
        "budget: tokens=%d duration=%dm iters=%d"
        % (
            doc.budget.estimated_tokens,
            doc.budget.estimated_duration_min,
            doc.budget.max_iterations,
        )
    )
    print("warnings:", doc._raw_frontmatter.get("_warnings"))
    print("errors:", doc._raw_frontmatter.get("_errors"))
    print("RESULT: VALID (0 fatal errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
