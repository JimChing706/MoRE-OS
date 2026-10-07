#!/usr/bin/env python3
"""Import the CS-FPS ITD into the running MoRE OS platform via HTTP.

Flow mirrors tests/test_e2e_native_tetris_itd_flow.py:
  parse -> validate -> import (auto_start) -> brief status poll.
"""
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8011"
ITD = "/Users/qnming/AI_Cample/QNMing_MoRE_OS_LIVE/deliverables/cs_fps/itd-cs-fps.md"
ENV = "/Users/qnming/AI_Cample/QNMing_MoRE_OS_LIVE/more_core/.env"


def load_key() -> str:
    for line in Path(ENV).read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s.startswith("MORE_API_KEY="):
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    import os
    return os.environ.get("MORE_API_KEY", "")


def main() -> int:
    key = load_key()
    if not key:
        print("NO KEY FOUND")
        return 1
    headers = {"Authorization": f"Bearer {key}"}
    md = Path(ITD).read_text(encoding="utf-8")

    with httpx.Client(base_url=BASE, headers=headers, timeout=30.0) as c:
        r = c.post("/api/v1/tasks/itd/parse", json={"content": md})
        pj = r.json()
        meta = (pj.get("document") or {}).get("metadata") or {}
        print("PARSE:", pj.get("status"), "| title:", meta.get("title"))

        r = c.post("/api/v1/tasks/itd/validate", json={"content": md})
        vj = r.json()
        s = vj.get("summary") or {}
        print(
            "VALIDATE: valid=%s | reqs=%s kc=%s ac=%s warnings=%s"
            % (
                vj.get("valid"),
                s.get("total_requirements"),
                s.get("total_kill_criteria"),
                s.get("total_acceptance_criteria"),
                s.get("total_warnings"),
            )
        )

        r = c.post("/api/v1/tasks/itd/import", json={"content": md, "auto_start": True})
        ij = r.json()
        print("IMPORT:", ij.get("status"), "| error:", ij.get("error"))
        task = ij.get("task") or {}
        tid = task.get("task_id")
        print("task_id:", tid)
        print("subtasks:", task.get("subtask_count"), task.get("subtask_ids"))
        print("warnings:", ij.get("warnings"))

        if ij.get("status") == "success" and tid:
            for _ in range(4):
                time.sleep(2)
                r = c.get(f"/api/v1/tasks/{tid}/status")
                sj = r.json()
                print("STATUS:", sj.get("status"), "| progress:", sj.get("progress"), "| error:", sj.get("error"))
                if sj.get("status") in ("completed", "failed", "partial"):
                    break
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
