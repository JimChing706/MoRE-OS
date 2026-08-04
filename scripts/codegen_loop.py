#!/usr/bin/env python3
"""MoRE OS 代码自动生成 Agentic Loop 控制器（docs/CODEGEN_LOOP_SPEC.md 的可执行固化）。

流程: Generate -> Self-Check -> Self-Audit -> (Fix 回灌) -> Lock，受 max_iterations 控制。
状态持久化到 docs/CODEGEN_RUNS/<run_id>.state.json，会话中断后可 --resume 续跑，
消除"循环依赖交互式会话"的单点故障。

用法:
    python scripts/codegen_loop.py start --task "任务描述"      # 新建运行
    python scripts/codegen_loop.py check [--run-id ID]          # 执行 Self-Check 门禁
    python scripts/codegen_loop.py audit --verdict pass|fail [--notes "..."]
    python scripts/codegen_loop.py lock --message "feat(x): ..."  # 提交 + 生成运行记录
    python scripts/codegen_loop.py status                        # 查看当前运行状态

Generate / Fix 由智能体（或人工）在工作树上完成；本控制器负责状态机、
门禁执行、防死循环裁决与最终落盘，保证任一环节中断后状态不丢失。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "docs" / "CODEGEN_RUNS"
APP_DIR = REPO_ROOT / "app"
DEFAULT_MAX_ITERATIONS = 3

SELF_CHECK_COMMANDS: list[tuple[str, list[str], Path]] = [
    ("pytest", [".venv/bin/python", "-m", "pytest", "more_core/tests", "-q"], REPO_ROOT),
    ("vitest", ["npx", "vitest", "run"], APP_DIR),
    ("tsc", ["npx", "tsc", "--noEmit"], APP_DIR),
    ("eslint", ["npx", "eslint", "src", "--max-warnings", "0"], APP_DIR),
    ("build", ["npx", "vite", "build"], APP_DIR),
]


@dataclass
class RunState:
    run_id: str
    task: str
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    iteration: int = 1
    phase: str = "generate"  # generate -> check -> audit -> lock -> done | escalated
    check_results: dict[str, bool] = field(default_factory=dict)
    audit_verdict: str = ""
    audit_notes: str = ""
    history: list[dict] = field(default_factory=list)
    commit_hash: str = ""

    @property
    def state_path(self) -> Path:
        return RUNS_DIR / f"{self.run_id}.state.json"

    def save(self) -> None:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, run_id: str) -> "RunState":
        data = json.loads((RUNS_DIR / f"{run_id}.state.json").read_text())
        return cls(**data)


def _latest_run_id() -> str:
    states = sorted(RUNS_DIR.glob("run_*.state.json"))
    if not states:
        sys.exit("没有进行中的运行；先执行 start。")
    return states[-1].name.removesuffix(".state.json")


def _resolve(run_id: str | None) -> RunState:
    return RunState.load(run_id or _latest_run_id())


def cmd_start(args: argparse.Namespace) -> None:
    run_id = f"run_{datetime.now():%Y%m%d_%H%M}"
    state = RunState(run_id=run_id, task=args.task, max_iterations=args.max_iterations)
    state.history.append({"ts": datetime.now().isoformat(), "event": "start", "task": args.task})
    state.save()
    print(f"已创建 {run_id}（phase=generate）。在工作树上完成生成后运行: codegen_loop.py check")


def cmd_check(args: argparse.Namespace) -> None:
    state = _resolve(args.run_id)
    results: dict[str, bool] = {}
    for name, cmd, cwd in SELF_CHECK_COMMANDS:
        print(f"[self-check] {name} ... ", end="", flush=True)
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        results[name] = proc.returncode == 0
        print("OK" if results[name] else "FAIL")
        if not results[name]:
            print(proc.stdout[-2000:] + proc.stderr[-2000:])
    state.check_results = results
    all_green = all(results.values())
    state.history.append(
        {"ts": datetime.now().isoformat(), "event": "check",
         "iteration": state.iteration, "results": results}
    )
    if all_green:
        state.phase = "audit"
        print("Self-Check 全绿 → 进入 Self-Audit（codegen_loop.py audit --verdict ...）")
    else:
        _advance_or_escalate(state, reason="self-check 未全绿")
    state.save()


def cmd_audit(args: argparse.Namespace) -> None:
    state = _resolve(args.run_id)
    state.audit_verdict = args.verdict
    state.audit_notes = args.notes or ""
    state.history.append(
        {"ts": datetime.now().isoformat(), "event": "audit",
         "iteration": state.iteration, "verdict": args.verdict, "notes": state.audit_notes}
    )
    if args.verdict == "pass":
        state.phase = "lock"
        print("Self-Audit 通过 → 可执行 Lock（codegen_loop.py lock --message ...）")
    else:
        _advance_or_escalate(state, reason="self-audit 存在 P1/P2 缺陷")
    state.save()


def _advance_or_escalate(state: RunState, reason: str) -> None:
    if state.iteration >= state.max_iterations:
        state.phase = "escalated"
        print(f"已达迭代上限 {state.max_iterations}（{reason}）→ 升级为 P0 人工接管，中间产物保留于 {state.state_path}")
    else:
        state.iteration += 1
        state.phase = "generate"
        print(f"{reason} → 进入 Fix 回灌（iteration {state.iteration}/{state.max_iterations}）")


def cmd_lock(args: argparse.Namespace) -> None:
    state = _resolve(args.run_id)
    if state.phase != "lock":
        sys.exit(f"当前 phase={state.phase}，未通过全部门禁，拒绝 Lock。")
    subprocess.run(["git", "add", "-A"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "commit", "-m", args.message], cwd=REPO_ROOT, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    state.commit_hash = commit
    state.phase = "done"
    state.history.append({"ts": datetime.now().isoformat(), "event": "lock", "commit": commit})
    _write_run_record(state)
    state.save()
    print(f"Lock 完成: {commit}；运行记录 {RUNS_DIR / (state.run_id + '.md')}")


def _write_run_record(state: RunState) -> None:
    checks = "\n".join(
        f"| {name} | {'✅' if ok else '❌'} |" for name, ok in state.check_results.items()
    )
    record = (
        f"# Codegen Loop 运行记录 — {state.run_id}\n\n"
        f"**任务**: {state.task}\n\n"
        f"**迭代**: {state.iteration}/{state.max_iterations} · "
        f"**Self-Audit**: {state.audit_verdict} {state.audit_notes}\n\n"
        f"## Self-Check\n\n| 检查 | 结果 |\n|------|------|\n{checks}\n\n"
        f"## Lock\n\n提交: `{state.commit_hash}`\n\n"
        f"## 轨迹\n\n```json\n{json.dumps(state.history, ensure_ascii=False, indent=2)}\n```\n"
    )
    (RUNS_DIR / f"{state.run_id}.md").write_text(record)


def cmd_status(args: argparse.Namespace) -> None:
    state = _resolve(args.run_id)
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("--task", required=True)
    p_start.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    p_start.set_defaults(func=cmd_start)

    p_check = sub.add_parser("check")
    p_check.add_argument("--run-id")
    p_check.set_defaults(func=cmd_check)

    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--verdict", choices=["pass", "fail"], required=True)
    p_audit.add_argument("--notes")
    p_audit.add_argument("--run-id")
    p_audit.set_defaults(func=cmd_audit)

    p_lock = sub.add_parser("lock")
    p_lock.add_argument("--message", required=True)
    p_lock.add_argument("--run-id")
    p_lock.set_defaults(func=cmd_lock)

    p_status = sub.add_parser("status")
    p_status.add_argument("--run-id")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
