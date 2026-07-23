# QNMing MoRE OS — Claude Code Rules

## Core Principles

1. 写代码前先思考。先说明假设，不要猜。
2. 简单优先。最少代码，不做投机式抽象。
3. 外科手术式修改。只改必须改的地方。
4. 目标驱动执行。先定义成功标准，然后循环直到验证通过。
5. 只把模型用于判断型任务（分类、草稿、总结、抽取）。代码能回答的，就让代码回答。
6. Token 预算不是建议。单任务 4000，单会话 30000。
7. 暴露冲突，不要折中平均。代码库里有两种模式就选一种。
8. 先读再写。先读 exports、调用方、共享工具。
9. 测试要验证意图，而不只是行为。
10. 每个重要步骤都要 checkpoint。
11. 匹配代码库约定。项目用 class components 就不要默默改成 hooks。
12. 失败要大声暴露。"成功完成"但 14% 记录被静默跳过是最糟糕的 bug。

---

## Project Context

- **版本**: v0.9.9 (`more_core/more_core/version.py`)
- **运行时**: Python 3.14, `.venv/`, macOS
- **构建系统**: setuptools (`more_core/pyproject.toml`)
- **Python 最低版本**: 3.10
- **API 端口**: 8011 (`make serve` / `make start`)
- **前端端口**: 3003 (`cd app && npm run dev`)
- **LLM Provider 链**: LM Studio (port 1234, primary) → Ollama (port 11434, fallback) → DeepSeek (API)
- **Frontend**: `app/` React + Vite + shadcn/ui + Tailwind CSS
- **License**: Apache-2.0

## Commands

### Backend (Python)

| Command | What |
|---------|------|
| `make install` | Install backend with API deps |
| `make install-dev` | Install with all dev deps (pytest, ruff, mypy) |
| `make serve` | Run API server (foreground, port 8011) |
| `make start` | Run API server (background daemon) |
| `make stop` | Stop background API server |
| `make test` | `pytest tests/ -v --tb=short` |
| `make test-cov` | pytest with coverage |
| `make lint` | `ruff check more_core/ tests/` |
| `make format` | `ruff format more_core/ tests/` |
| `make typecheck` | `mypy more_core/` |

### Frontend

| Command | What |
|---------|------|
| `cd app && npm run dev` | Dev server (port 3003) |
| `cd app && npm run lint` | ESLint |
| `cd app && npm test` | Vitest |
| `cd app && npm run build` | Production build |
| `cd app && npx tsc -b --noEmit` | TypeScript check |

### Health / Ops

| Command | What |
|---------|------|
| `make health` | `curl localhost:8011/api/v1/health` |
| `make status` | Show running processes & port usage |
| `make check-env` | Verify Python/node/LMStudio/Ollama |
| `make clean` | Remove `__pycache__`, build artifacts, logs |

### Manual API start

```bash
.venv/bin/python -m more_core.cli serve --host 0.0.0.0 --port 8011
```

---

## Architecture

### L0–L5 Pipeline

The system routes tasks through an ordered pipeline of layers:

- **L0 (Execution)**: Direct tool/action execution, no LLM
- **L1 (Orchestration)**: Multi-step task decomposition, LLM calls
- **L2 (Evolution)**: Self-improvement, benchmark-driven optimization
- **L3 (Symbolic)**: Formal reasoning, symbolic math, logic
- **L4 (Cognition)**: Deep reasoning, context analysis, planning
- **L5 (Metacognition)**: Meta-level oversight, strategy selection

Pipeline selection is task-type aware (see `router/layer_router.py`). Default pipelines:

```
SELF_IMPROVEMENT:   L5 → L2 → L1 → L0
MATH_REASONING:     L4 → L3 → L1 → L0
CODE_GENERATION:    L4 → L3 → L1 → L0
ARCHITECTURE_DESIGN: L5 → L4 → L3 → L1 → L0
```

### Module Map

| Module | Path | Role |
|--------|------|------|
| **Orchestrator** | `runtime/orchestrator.py` | Wires all subsystems, lifecycle |
| **API Routers** | `api/routers/` (19 routers) | REST endpoints |
| **LLM Manager** | `llm/manager.py` | Multi-provider + fallback + LRU cache |
| **Layer Router** | `router/layer_router.py` | Difficulty-aware pipeline |
| **MCP** | `mcp/` | Model Context Protocol client/server |
| **A2A** | `a2a/` | Agent-to-Agent protocol |
| **Memory** | `memory/` | Persistent memory store |
| **Hands** | `hands/` | Tool/action execution (registry, manager) |
| **Plugins** | `plugins/` | 3 industry plugins (mahjong, minesweeper*) |
| **Channels** | `channels/` | Multi-channel I/O (reconnect, manager) |
| **Sandbox** | `sandbox/` | Secure execution sandbox |
| **Security** | `security/` | RBAC, taint tracking, output filter |
| **Evolution** | `evolution/` | Benchmark, DGM, archive |
| **Governance** | `governance/` | Audit log, policy enforcer |
| **Planning** | `planning/` | Token prediction, plan coordination |

### Data Layer

- **DB files**: `data/evolution.db`, `data/memory.db`, `data/outputs.db`
- **dotenv**: `more_core/.env` + `app/.env` (auto-loaded)

### Execution Flow

1. API 接收请求 → `api/routers/*.py` 验证输入
2. `orchestrator.execute()` 创建 `TaskRequest`
3. `LayerRouter.route()` 根据 `TaskType` 选择 pipeline
4. Layers 按序执行：每层可调用 LLM、tools、memory、plugins
5. 结果沿 pipeline 传回，`TaskResult` 返回给调用方

### Utility Scripts

| Script | Function |
|--------|----------|
| `bash scripts/health_check.sh` | Full-stack health check |
| `./run-local-ai.sh start` | Service launcher (API + local models) |
| `scripts/dev-workflow.sh` | Code quality workflow (lint/format/test) |
| `scripts/model-selector.sh` | Task-aware model recommendation |
| `scripts/session-manager.sh` | Session list/resume/cleanup |
| `scripts/lmstudio-chat.py` | Direct LM Studio chat tool |

### Environment Variables (core)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MORE_LMSTUDIO_ENDPOINT` | `http://localhost:1234/v1` | Primary LLM provider |
| `MORE_LMSTUDIO_MODEL` | — | Model name in LM Studio |
| `MORE_OLLAMA_ENDPOINT` | `http://localhost:11434` | Fallback LLM provider |
| `MORE_OLLAMA_MODEL` | — | Model name in Ollama |
| `MORE_DEEPSEEK_API_KEY` | — | Cloud API key |
| `MORE_LLM_FALLBACK_CHAIN` | `lmstudio,ollama` | Provider failover order |
| `MORE_ENABLE_SYMBOLIC` | `1` | Enable L3 symbolic reasoning |
| `MORE_ENABLE_EVOLUTION` | `1` | Enable L2 self-improvement |
| `MORE_ENABLE_METACOGNITION` | `1` | Enable L5 metacognition |
| `MORE_MEMORY_DB` | `data/memory.db` | Memory/SQLite path |
| `MORE_EVOLUTION_DB` | `data/evolution.db` | Evolution/SQLite path |

Full template: `more_core/.env.template`

---

## Coding Conventions

### Python

- **Line length**: 100 (ruff config)
- **Target**: Python 3.10+
- **Type annotations**: Required via mypy strict mode
- **Formatting**: `ruff format` only (no black/isort)
- **Imports**: Standard library → third-party → local (groups separated by blank line). Within `more_core/` package, always use relative imports (`from ..x.y import Z`).
- **Async**: `asyncio` with `asyncio_mode = auto` in tests
- **Error handling**: Raise `MoREError` subclasses, not generic `Exception`. Hierarchy: `MoREError` → `PluginError`, `LLMError`, `SandboxError`, `GovernanceError`, `RoutingError` (see `core/errors.py`).
- **Logging**: Use `logging.getLogger(__name__)`, not `print()`. Logger name: `"more_core.<module>"`.
- **Dataclasses**: Prefer `@dataclass` for internal data containers, `BaseModel` (pydantic) for API schemas and cross-boundary types
- **Settings**: Configuration via pydantic `BaseModel` in `core/config.py`, loaded from env vars + `.env` file (auto-loaded via `_load_dotenv()`)
- **Service wiring**: All subsystems register via `ServiceRegistry` (singleton in `core/service_registry.py`). Orchestrator owns lifecycle.

### Tests

- **Framework**: pytest + pytest-asyncio
- **Location**: `more_core/tests/`
- **Naming**: `test_*.py`, `Test*` classes, `test_*` functions
- **Async**: Auto-detected (don't add `@pytest.mark.asyncio`)
- **Run**: `make test` or `cd more_core && .venv/bin/python -m pytest tests/ -v --tb=short`

### Frontend (app/)

- **Framework**: React + TypeScript + Vite
- **Styling**: Tailwind CSS + shadcn/ui components
- **Type checking**: `npx tsc -b --noEmit` before commit
- **Testing**: Vitest (`npm test`)

### Git

- **Branch**: `main` (stable) / `develop` (daily) / `feature/<name>` / `fix/<name>` / `plugin/<name>`
- **Commit**: [Conventional Commits](https://www.conventionalcommits.org/), e.g. `feat(core):`, `fix(llm):`, `refactor(layers):`, `test(tools):`, `docs(readme):`, `plugin(mahjong):`

---

## Known Issues

- 扫雷 GUI (8080) 端口被系统占用，不影响核心
- LM Studio 大模型响应慢 (~30s)，生产用 Ollama 或 DeepSeek
- `minesweeper_game` 依赖 `minesweeper_agent`，关闭顺序需反向依赖解析
- CI 中 mypy 失败不阻断 (`mypy more_core/ || true`)
- mypy 配置 `ignore_missing_imports = true`

## Debugging

- API logs: `/tmp/more-os-api.log`
- Frontend logs: `/tmp/more-os-frontend.log`
- Health check: `curl localhost:8011/api/v1/health`
- Port check: `lsof -i :8011 -i :3003`
- LLM provider check: `curl -s --max-time 2 http://localhost:1234/v1/models` (LM Studio)
- Project memory: `.remember/` directory (AI persistent logs)
