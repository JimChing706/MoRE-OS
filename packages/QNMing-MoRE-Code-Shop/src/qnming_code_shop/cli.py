"""QNMing MoRE Code Shop 命令行入口。

    code-shop generate -q "实现 Python 函数 is_palindrome(s)"   # 生成 + 校验 + 记账
    code-shop preflight                                        # LLM 链路预检
    code-shop metrics                                          # token / 延迟 / 成功率
    code-shop deliveries                                       # 交付成功率与阻断原因
    code-shop serve --host 127.0.0.1 --port 8011               # 起完整 API
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from . import PRODUCT_NAME, PRODUCT_TAGLINE, __version__


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _cmd_generate(args: argparse.Namespace) -> int:
    from .facade import generate_code

    result = asyncio.run(
        generate_code(args.query, actor=args.actor, candidates=args.candidates,
                      timeout_s=args.timeout)
    )
    d = result.to_dict()
    gates = d.pop("gates", {})
    output = d.pop("output", "")

    print("=" * 66)
    print(f"状态      : {d['status']}   闸门: {'通过' if gates.get('passed') else '未通过'}")
    print(f"任务      : {d['task_id']}   tokens: {d['tokens_used']}")
    if d.get("verdict"):
        print(f"控制器裁决: {d['verdict']}" + (f"  原因: {d['escalation'].get('cause')}"
                                          if d.get("escalation") else ""))
    for f in gates.get("findings", []):
        mark = "✓" if f.get("ok") else "✗"
        print(f"  {mark} {f.get('gate'):12s} {f.get('detail','')[:56]}")
    stages = d.get("stage_timings", {}).get("layers_ms") or {}
    if stages:
        print("阶段耗时  : " + "  ".join(f"{k}={v}ms" for k, v in stages.items()))
    print("=" * 66)
    if args.json:
        _print_json(d)
    else:
        print(output)
    return 0 if result.ok else 1


def _cmd_preflight(_args: argparse.Namespace) -> int:
    from .facade import preflight

    report = asyncio.run(preflight())
    print(f"{PRODUCT_NAME} LLM 链路预检")
    print(f"  状态: {'OK' if report.get('ok') else 'WARN'}   "
          f"降级: {report.get('degraded')}   兜底链: {report.get('chain_registered')}")
    for p in report.get("providers", []):
        print(f"  - {p['name']:10s} model={p['configured_model']:28s} "
              f"exists={p['model_present']} models={p['models_available']}")
    for w in report.get("warnings", []):
        print(f"  ⚠ {w}")
    return 0 if report.get("ok") else 1


def _cmd_metrics(args: argparse.Namespace) -> int:
    from .facade import delivery_stats, metrics

    _print_json({
        "llm": metrics(args.window),
        "delivery": delivery_stats(args.window),
    })
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """起完整 API（复用内核 create_app）。"""
    import uvicorn

    from more_core.api.server import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="code-shop", description=f"{PRODUCT_NAME} — {PRODUCT_TAGLINE}")
    p.add_argument("--version", action="version", version=f"{PRODUCT_NAME} {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="生成代码并跑完整校验/记账链路")
    g.add_argument("-q", "--query", required=True, help="自然语言需求")
    g.add_argument("--actor", default="code-shop", help="调用主体（写入台账）")
    g.add_argument("--candidates", type=int, default=1, help="best-of-k 候选数")
    g.add_argument("--timeout", type=float, default=300.0, help="任务超时（秒）")
    g.add_argument("--json", action="store_true", help="额外输出结构化结果")
    g.set_defaults(func=_cmd_generate)

    pf = sub.add_parser("preflight", help="LLM 链路预检（provider/模型/兜底链）")
    pf.set_defaults(func=_cmd_preflight)

    m = sub.add_parser("metrics", help="运行指标：token / 延迟 / 成功率 / 交付")
    m.add_argument("--window", type=int, default=3600, help="统计窗口（秒）")
    m.set_defaults(func=_cmd_metrics)

    s = sub.add_parser("serve", help="启动完整 API 服务")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8011)
    s.set_defaults(func=_cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
