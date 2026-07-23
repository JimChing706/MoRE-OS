"""QNMing MoRE OS — Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


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
            except Exception as exc:
                print(f"  Error: {exc}")
    finally:
        await core.stop()


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

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        _serve(args.host, args.port)
    elif args.cmd == "mcp-serve":
        _mcp_serve()
    elif args.cmd == "run":
        asyncio.run(_run_once(args.type, args.query))
    elif args.cmd == "chat":
        asyncio.run(_chat_interactive(args.type))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
