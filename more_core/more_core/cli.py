"""QNMing MoRE OS — Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型检查期导入，避免 CLI 冷启动成本
    from .security.api_key_store import APIKeyStore


def _serve(host: str, port: int) -> None:
    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        print("Install with: pip install 'qnming-more-os[api]'", file=sys.stderr)
        sys.exit(1)

    from .api.server import create_app
    from .runtime.orchestrator import MoRECore

    core = MoRECore.from_env()
    app = create_app(core)
    uvicorn.run(app, host=host, port=port)


async def _run_once(task_type: str, query: str) -> None:
    from .core.types import TaskRequest, TaskType
    from .runtime.orchestrator import MoRECore

    core = MoRECore.from_env()
    await core.start()
    try:
        result = await core.execute(TaskRequest(type=TaskType(task_type.lower()), query=query))
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
    finally:
        await core.stop()


def _mcp_serve() -> None:
    """Run MCP server on stdio (for Codex CLI / Claude Code integration)."""
    asyncio.run(_mcp_serve_stdio())


async def _mcp_serve_stdio() -> None:
    from .runtime.orchestrator import MoRECore

    core = MoRECore.from_env()
    await core.start()
    try:
        srv = core.mcp_server
        await srv.run_stdio()
    finally:
        await core.stop()


async def _chat_interactive(task_type: str = "nlp_task") -> None:
    """Interactive chat mode — DeepSeek TUI style."""
    from .core.types import TaskRequest, TaskType
    from .runtime.orchestrator import MoRECore

    BLUE = "\033[34m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

    print(f"{BLUE}╔══════════════════════════════════════════╗{RESET}")
    print(f"{BLUE}║  MoRE OS — Interactive Chat (type /quit){RESET}")
    print(f"{BLUE}╚══════════════════════════════════════════╝{RESET}")
    print()

    core = MoRECore.from_env()
    await core.start()
    try:
        while True:
            try:
                user_input = input(f"{GREEN}▸ {RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue
            if user_input.lower() in ("/quit", "/exit", "/q"):
                print("Goodbye.")
                break

            print(f"{CYAN}Thinking...{RESET}", end="\r")
            try:
                result = await core.execute(
                    TaskRequest(type=TaskType(task_type.lower()), query=user_input)
                )
                print(" " * 20, end="\r")
                output = result.output
                if result.reasoning_chain:
                    layers = " → ".join(s.layer.value for s in result.reasoning_chain)
                    print(f"{CYAN}[{layers} | {result.performance.total_duration_ms:.0f}ms]{RESET}")
                print(output)
                print()
            except Exception as exc:  # noqa: BLE001
                print(f"  Error: {exc}")
    finally:
        await core.stop()


# ---------------------------------------------------------------------------
# 补缺环节：api-key generate / validate / inject / rotate-proof CLI
# ---------------------------------------------------------------------------


def _cmd_api_key_generate(args: argparse.Namespace) -> int:
    from .security.api_key_ops import APIKeyKind, generate_api_key, validate_api_key_report

    strength: APIKeyKind = "compat"
    if args.hex:
        strength = "hex"
    elif args.modern or args.strength in {"modern", "256bit"}:
        strength = "modern"

    key = generate_api_key(strength=strength, enforce_prefix=args.with_prefix)
    # 补缺校验：立即用 validate_api_key_report 打印 7 项合规摘要（不打印密钥本体到 stderr）
    rep = validate_api_key_report(key, require_prefix=args.strict)
    if args.output_env:
        from .security.api_key_ops import inject_api_key_into_env

        env_path, backup_path, prev = inject_api_key_into_env(
            key, args.output_env, backup=not args.no_backup, strict=args.strict
        )
        print(f"Wrote MORE_API_KEY to {env_path}")
        if backup_path:
            print(f"Previous value backed up to {backup_path} (prev len={len(prev)})")
    else:
        print(key)
    if args.verbose:
        print(json.dumps(rep.as_dict(), indent=2, ensure_ascii=False), file=sys.stderr)
    return 0


def _cmd_api_key_validate(args: argparse.Namespace) -> int:
    import os as _os

    from .security.api_key_ops import ENV_PATHS, validate_api_key_report

    key = args.key
    if not key:
        key = _os.getenv("MORE_API_KEY", "")
    if not key and args.from_env:
        for cand in ENV_PATHS:
            if not cand.exists():
                continue
            for ln in cand.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = ln.strip()
                if s.startswith("MORE_API_KEY="):
                    v = s.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        key = v
                        break
            if key:
                break
    if not key:
        print(
            "ERROR: no key supplied (pass --key, set MORE_API_KEY, or use --from-env)",
            file=sys.stderr,
        )
        return 2

    rep = validate_api_key_report(
        key, require_prefix=args.strict, min_length=args.min_length or None
    )
    if args.rotate_event:
        # Best-effort provenance.mark — 补缺测试阶段允许 provenance DB 不存在
        try:
            from .core.guardrails.provenance_audit import ProvenanceLayer

            layer = ProvenanceLayer()
            layer.enroll("more_api_key_rotated_admin_event", channel="pending")
            layer.mark(
                "more_api_key_rotated_admin_event",
                channel="native_planner_loop",
                token_count=32,
                payload={
                    "event": "more_api_key_validated",
                    "length": rep.length,
                    "entropy_bits": rep.entropy_bits,
                },
            )
        except Exception:  # noqa: BLE001, S110
            pass
    out = rep.as_dict()
    out["key_prefix"] = (key[:8] + "***") if key else ""
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if rep.valid else 1


def _cmd_api_key_inject(args: argparse.Namespace) -> int:
    from .security.api_key_ops import APIKeyKind, generate_api_key, inject_api_key_into_env

    key = args.key
    if not key:
        strength: APIKeyKind = "hex" if args.hex else ("modern" if args.modern else "compat")
        key = generate_api_key(strength=strength, enforce_prefix=args.with_prefix)
    env_path, backup_path, prev = inject_api_key_into_env(
        key, args.env or None, backup=not args.no_backup, strict=args.strict
    )
    print(f"injected MORE_API_KEY (len={len(key)} prev_len={len(prev)}) into {env_path}")
    if backup_path:
        print(f"backup -> {backup_path}")
    return 0


def _cmd_api_key_rotate_proof(args: argparse.Namespace) -> int:
    import os as _os

    from .security.api_key_ops import (
        generate_api_key,
        sign_rotation_proof,
        verify_rotation_proof,
    )

    master = args.master_key or _os.getenv("MORE_MASTER_ROTATION_KEY", "")
    if not master:
        print("ERROR: pass --master-key or set MORE_MASTER_ROTATION_KEY", file=sys.stderr)
        return 2
    new_key = args.new_key or generate_api_key(
        strength=("modern" if args.modern else "compat"), enforce_prefix=False
    )
    proof = sign_rotation_proof(
        master_key=master,
        new_key=new_key,
        revoke_old_in_seconds=args.revoke_seconds,
    )
    ok = verify_rotation_proof(
        master_key=master,
        proof=proof,
        new_key=new_key,
        revoke_old_in_seconds=args.revoke_seconds,
    )
    payload = {
        "new_key_len": len(new_key),
        "revoke_old_in_seconds": args.revoke_seconds,
        "rotation_proof": proof,
        "verify": ok,
    }
    if args.include_key:
        payload["new_key"] = new_key
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# 受管密钥生命周期：issue / list / rotate / revoke（存储 + 作用域 + 过期）
# ---------------------------------------------------------------------------


def _ak_store() -> APIKeyStore:
    from .security.api_key_store import APIKeyStore

    return APIKeyStore()


def _cmd_api_key_issue(args: argparse.Namespace) -> int:
    scopes = [s.strip() for s in (args.scopes or "").split(",") if s.strip()]
    ttl = args.ttl_seconds
    if ttl is None and args.ttl_days is not None:
        ttl = int(args.ttl_days * 86400)
    raw, record = _ak_store().register(
        label=args.label or "",
        scopes=scopes or ["tasks:execute"],
        ttl_seconds=ttl,
        owner=getattr(args, "owner", "") or "",
        consumer=getattr(args, "consumer", "") or "",
        purpose=getattr(args, "purpose", "") or "",
        issued_by="cli",
        channel="cli",
        quota_per_min=getattr(args, "quota_per_min", None),
    )
    print(f"key_id  : {record.key_id}")
    print(f"owner   : {record.owner or '-'}  consumer: {record.consumer or '-'}")
    print(f"scopes  : {','.join(record.scopes)}")
    print(f"quota   : {record.quota_per_min or 'unlimited'} /min")
    print(f"expires : {record.expires_at or 'never'}")
    print(f"secret : {raw}")
    print("store this secret now — it will not be shown again")
    return 0


def _cmd_api_key_list(args: argparse.Namespace) -> int:
    store = _ak_store()
    print(
        json.dumps(
            {
                "keys": [r.as_dict() for r in store.list_keys(include_inactive=args.all)],
                "stats": store.stats(),
                "db": str(store.db_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_api_key_revoke(args: argparse.Namespace) -> int:
    ok = _ak_store().revoke(args.key_id)
    print(
        f"revoked {args.key_id}" if ok else f"no such active key: {args.key_id}",
        file=sys.stderr if not ok else sys.stdout,
    )
    return 0 if ok else 1


def _cmd_api_key_rotate(args: argparse.Namespace) -> int:
    result = _ak_store().rotate(args.key_id, grace_seconds=args.grace_seconds)
    if result is None:
        print(f"no such key: {args.key_id}", file=sys.stderr)
        return 1
    raw, record = result
    print(f"rotated_from: {args.key_id}")
    print(f"new_key_id  : {record.key_id}")
    print(f"grace_s     : {args.grace_seconds}")
    print(f"secret      : {raw}")
    print("store this secret now — it will not be shown again")
    return 0


def _cmd_api_key_usage(args: argparse.Namespace) -> int:
    store = _ak_store()
    if store.get(args.key_id) is None:
        print(f"no such key: {args.key_id}", file=sys.stderr)
        return 1
    print(json.dumps(store.usage(args.key_id, window_s=args.window), indent=2, ensure_ascii=False))
    return 0


def _cmd_api_key_overview(args: argparse.Namespace) -> int:
    store = _ak_store()
    print(
        json.dumps(
            store.usage_overview(window_s=args.window, top=args.top), indent=2, ensure_ascii=False
        )
    )
    return 0


def _cmd_api_key_attention(args: argparse.Namespace) -> int:
    store = _ak_store()
    print(
        json.dumps(
            store.attention(expiry_days=args.expiry_days, stale_days=args.stale_days),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _build_api_key_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p_ak = sub.add_parser(
        "api-key", help="API-key generate / validate / inject / rotate-proof (测试补缺专用)"
    )
    ak_sub = p_ak.add_subparsers(dest="ak_cmd", required=True)

    p_gen = ak_sub.add_parser("generate", help="Generate a new API key (默认 46-char compat 格式).")
    p_gen.add_argument(
        "--strength", choices=["compat", "modern", "hex", "256bit"], default="compat"
    )
    p_gen.add_argument(
        "--hex", action="store_true", help="Alias for --strength=hex (64 位纯十六进制)."
    )
    p_gen.add_argument(
        "--modern", action="store_true", help="Alias for --strength=modern (sk-more-os- 前缀)."
    )
    p_gen.add_argument(
        "--with-prefix", action="store_true", help="给 compat/hex 密钥强制加上 sk-more-os- 前缀."
    )
    p_gen.add_argument(
        "--strict", action="store_true", help="Inject/validate 时强制 MORE_REQUIRE_API_KEY=1 规则."
    )
    p_gen.add_argument(
        "--output-env", metavar="PATH", help="直接写入 .env 文件 (默认 more_core/.env 回退链)."
    )
    p_gen.add_argument(
        "--no-backup", action="store_true", help="写入 .env 时跳过自动 .bak.YYYYMMDD_HHMMSS 备份."
    )
    p_gen.add_argument(
        "--verbose", action="store_true", help="向 stderr 输出 validate 摘要 (熵/长度/前缀)."
    )
    p_gen.set_defaults(func=_cmd_api_key_generate)

    p_val = ak_sub.add_parser("validate", help="Validate a key 与更业务侧 6 项合规报告.")
    p_val.add_argument("--key", help="待校验密钥；留空则读 MORE_API_KEY envvar")
    p_val.add_argument(
        "--from-env",
        action="store_true",
        help="当 --key/envvar 都空时自动回退 ENV_PATHS .env 链解析.",
    )
    p_val.add_argument("--strict", action="store_true", help="必须有 sk-more-os- 前缀.")
    p_val.add_argument("--min-length", type=int, default=None, help="自定义最小长度 (默认=16).")
    p_val.add_argument(
        "--rotate-event",
        action="store_true",
        help="写入 provenance.mark 作为 more_api_key_rotated 审计事件.",
    )
    p_val.set_defaults(func=_cmd_api_key_validate)

    p_inj = ak_sub.add_parser("inject", help="把一个已有/即时生成的新密钥注入 .env 链，自动备份")
    p_inj.add_argument("--key", help="已有密钥；留空则用 generate 生成一个")
    p_inj.add_argument("--env", metavar="PATH", help="目标 .env 路径（留空走 ENV_PATHS 回退）")
    p_inj.add_argument("--hex", action="store_true")
    p_inj.add_argument("--modern", action="store_true")
    p_inj.add_argument("--with-prefix", action="store_true")
    p_inj.add_argument("--strict", action="store_true")
    p_inj.add_argument("--no-backup", action="store_true")
    p_inj.set_defaults(func=_cmd_api_key_inject)

    p_rp = ak_sub.add_parser("rotate-proof", help="为 HTTP /admin/api-key/rotate 生成 HMAC proof")
    p_rp.add_argument("--master-key", help="或通过 MORE_MASTER_ROTATION_KEY 注入")
    p_rp.add_argument("--new-key", help="留空则本命令直接生成 compat/modern 密钥")
    p_rp.add_argument("--modern", action="store_true")
    p_rp.add_argument("--revoke-seconds", type=int, default=3600)
    p_rp.add_argument(
        "--include-key", action="store_true", help="输出结果里带上 new_key（仅本地安全测试用）"
    )
    p_rp.set_defaults(func=_cmd_api_key_rotate_proof)

    p_issue = ak_sub.add_parser(
        "issue", help="签发受管密钥（存储 + 作用域 + 过期，仅显示一次明文）"
    )
    p_issue.add_argument("--label", default="", help="用途标签，例如 ci / dashboard")
    p_issue.add_argument(
        "--scopes", default="tasks:execute", help="逗号分隔作用域，默认 tasks:execute"
    )
    p_issue.add_argument("--ttl-days", type=float, default=None, help="有效期（天）；留空=永不过期")
    p_issue.add_argument(
        "--ttl-seconds", type=int, default=None, help="有效期（秒），优先于 --ttl-days"
    )
    p_issue.add_argument("--owner", default="", help="归属团队/租户")
    p_issue.add_argument("--consumer", default="", help="使用方服务名，例如 ci-runner / dashboard")
    p_issue.add_argument("--purpose", default="", help="用途说明")
    p_issue.add_argument(
        "--quota-per-min", type=int, default=None, help="每分钟调用上限（留空=不限）"
    )
    p_issue.set_defaults(func=_cmd_api_key_issue)

    p_list = ak_sub.add_parser("list", help="列出受管密钥元数据（不含明文）")
    p_list.add_argument("--all", action="store_true", help="包含已过期/已吊销")
    p_list.set_defaults(func=_cmd_api_key_list)

    p_revoke = ak_sub.add_parser("revoke", help="立即吊销受管密钥")
    p_revoke.add_argument("key_id")
    p_revoke.set_defaults(func=_cmd_api_key_revoke)

    p_rotate = ak_sub.add_parser("rotate", help="轮换受管密钥（旧密钥保留 grace 秒）")
    p_rotate.add_argument("key_id")
    p_rotate.add_argument("--grace-seconds", type=int, default=3600)
    p_rotate.set_defaults(func=_cmd_api_key_rotate)

    p_usage = ak_sub.add_parser("usage", help="查看单把密钥的用量报表（调用/失败/延迟/tokens）")
    p_usage.add_argument("key_id")
    p_usage.add_argument("--window", type=int, default=86400, help="统计窗口（秒），默认 24h")
    p_usage.set_defaults(func=_cmd_api_key_usage)

    p_ov = ak_sub.add_parser("overview", help="按密钥聚合的用量总览")
    p_ov.add_argument("--window", type=int, default=86400)
    p_ov.add_argument("--top", type=int, default=20)
    p_ov.set_defaults(func=_cmd_api_key_overview)

    p_att = ak_sub.add_parser("attention", help="即将过期 / 从未使用 / 待清理 的密钥")
    p_att.add_argument("--expiry-days", type=int, default=14)
    p_att.add_argument("--stale-days", type=int, default=30)
    p_att.set_defaults(func=_cmd_api_key_attention)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="more-os", description="QNMing MoRE OS — Agent OS CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Start the HTTP API server.")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8001)

    sub.add_parser("mcp-serve", help="Start MCP server on stdio (for Codex/Claude integration).")

    p_run = sub.add_parser("run", help="Execute a single task and print the result.")
    p_run.add_argument("--type", default="nlp_task")
    p_run.add_argument("--query", "-q", required=True, help="Prompt to send to MoRE Core.")

    p_chat = sub.add_parser("chat", help="Interactive chat mode (DeepSeek TUI style).")
    p_chat.add_argument("--type", default="nlp_task", help="Task type for the conversation.")

    _build_api_key_subparser(sub)

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        _serve(args.host, args.port)
    elif args.cmd == "mcp-serve":
        _mcp_serve()
    elif args.cmd == "run":
        asyncio.run(_run_once(args.type, args.query))
    elif args.cmd == "chat":
        asyncio.run(_chat_interactive(args.type))
    elif args.cmd == "api-key":
        return int(args.func(args) or 0)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
