# Changelog

All notable changes to **QNMing MoRE OS** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-05-21

### Security

- **Redacted leaked OpenAI API Key** — `app/server/.env:15` contained real `sk-proj-*` key; replaced with placeholder
- **Redacted API Key in audit report** — `docs/reports/Code_Audit_Report.md` also contained full key; replaced with `****REDACTED****`
- **Added root `.gitignore`** — prevents committing `.env`, `venv/`, `__pycache__/`, `node_modules/`, `dist/`, `.DS_Store`, logs

### Fixed

- **1257 ruff lint errors auto-fixed** — import sorting (I001), trailing whitespace (W291/W293), missing newlines (W292), deprecated `typing` imports (UP035/UP006/UP045), unnecessary quotes in type annotations (UP037), unsorted `__all__` (RUF022), unnecessary key checks before dict access (RUF019), explicit conversion flags (RUF010), deprecated `Deque`/`Dict`/`List`/`Set` (UP006)
- **348 design-level warnings remain** — `PLC0415` (imports inside functions, intentional for lazy loading), `TRY003` (long exception messages), `PLR2004` (magic values), `FBT001/002` (boolean args), `PLR0913/0915` (too many args/statements) — these are architectural style issues, not bugs

## [0.7.0] - 2026-05-21

### Fixed

- **F821 undefined `web`** in `channels/http.py` — `WebhookServer` methods referenced `web` module imported only inside `start()`; fixed by storing as `self._web` instance attribute
- **F821 undefined `ToolRegistry`** in `tools/builtins.py` — type annotation `registry: "ToolRegistry"` had no matching import; added to `.registry` imports
- **E402 module-level import after code** in 3 channel adapters — `qq_adapter.py`, `webhook_adapter.py`, `wechat_adapter.py` had `from .base import ...` after `_log = logging.getLogger()`; moved imports to top
- **F841 unused variable `adapter`** in `channels/manager.py:43` — `pop()` result captured but never read; removed assignment
- **F841 unused variable `result`** in `cron/trigger.py:231` — handler return value captured but never used; removed assignment
- **F841 unused variable `fired`** in `metacognition/metacognition.py:41` — `fired_rules` captured but only `violations` used; removed assignment
- **F841 unused variable `context`** in `tools/builtins.py:75` — grep context param read but never used; removed
- **F841 unused variables `arg_names`, `kwonly`** in `tools/codex/indexer.py:134,137` — computed but never referenced; removed
- **F401 unused import `ToolDefinition`** in `mcp/registry.py:172` — imported but never referenced in function body; replaced with `importlib.util.find_spec` check
- **`alert()` replaced with `toast`** in `ProjectOutputReview.tsx` — 2 `alert()` calls replaced with `sonner` toast notifications (success/error)

## [0.6.0] - 2026-05-21

### Security

- **Removed `eval()` arbitrary code execution** — `workflows/engine.py` condition check replaced with `_safe_eval_condition()` using AST allowlist (comparisons, boolean ops, attribute access only)
- **Fixed API key timing attack** — `app/server/src/main.py` now uses `hmac.compare_digest()` for BFF API key comparison (2 locations)
- **Fixed frontend BFF authentication bypass** — `apiService.ts` now sends `Authorization: Bearer` header on all requests including SSE streams, reads `VITE_BFF_API_KEY` env var
- **Removed Grafana default password** — `docker-compose.yml` no longer falls back to hardcoded `morev3admin`

### Fixed

- **Undefined names in channel adapters** — added `ChannelConfig`, `ChannelUser`, `ChannelMessage`, `ChannelType` types to `channels/base.py`; updated `discord.py`, `slack.py`, `telegram.py`, `http.py` to import from base
- **Missing `import httpx`** in `skills/code_skills.py`
- **Frontend API endpoint mismatch** — all 10+ calls changed from `/api/v1/*` to `/api/*` matching BFF routes (`apiService.ts`, `dashboard.ts`, `moreEngine.ts`)
- **Non-existent endpoint** — `/api/v1/monitor/dashboard` replaced with real `/api/tasks/history`
- **Wrong import in minesweeper_game** — `from .agent` → `from plugins.minesweeper_agent.agent`
- **Deprecated `asyncio.get_event_loop().time()`** in `plugins/minesweeper_game/tools.py` → `get_running_loop().time()`
- **Duplicate Plugin classes** — removed 170+ lines of duplicated Plugin class from `minesweeper_game/__init__.py` and `minesweeper_agent/__init__.py` (canonical version in `main.py`)
- **Hardcoded `localhost:8001` URLs** — 7 frontend files now use `VITE_API_BASE` env var
- **Inconsistent env var names** — unified `VITE_API_BASE_URL` → `VITE_API_BASE`
- **`print()` in channel adapters** — 8 print statements replaced with proper `_log` calls (`discord_adapter.py`, `telegram_adapter.py`)
- **Corrupted `scripts/run_demo.py`** — recreated as valid Python minesweeper auto-play demo
- **Deleted garbage file** — `more_core/new_file.py` removed
- **101 unused imports** auto-fixed via `ruff check --fix`

## [0.5.0] - 2026-05-21

### Added

- **Modular API routers** — `api/server.py` refactored from 1548-line monolith into 16 focused routers under `api/routers/`
- **RBAC middleware** on BFF server — `MORE_ENABLE_RBAC=1` enforces role-based access on write endpoints
- **BFF authentication** — `_require_bff_api_key` dependency guards `POST /api/tasks/*` and `/api/redis/clear`
- **Frontend test infrastructure** — Vitest + React Testing Library + jsdom setup with `format.test.ts`
- **`.dockerignore`** for frontend build — excludes `node_modules`, `dist`, env files, IDE configs

### Fixed

- **Removed `mahjong/` from core package** — 5-file multiplayer game module moved out of domain-neutral kernel
- **Deprecated `asyncio.get_event_loop()`** — replaced with `asyncio.get_running_loop()` in `mcp/server.py`, `mcp/transport.py`, `minesweeper_agent/tools.py`
- **Deprecated `asyncio.new_event_loop()` pattern** — replaced with `asyncio.run()` via `ThreadPoolExecutor` in `minesweeper_agent/agent.py`
- **Deprecated `@app.on_event("startup")`** — replaced with `lifespan` context manager in `minesweeper_game/gui_server.py`
- **Deprecated `datetime.utcnow()`** — all instances replaced with `datetime.now(timezone.utc)` across `minesweeper_game/` and `api/`
- **Duplicate `GameSession` class** — removed from `gui_server.py`, unified in `state_manager.py`
- **Duplicate `get_difficulties` route** — removed dead duplicate endpoint in `gui_server.py`
- **Duplicate `import_time()` function** — removed from `game_engine.py`
- **File handle leaks** — 4 `open().read()` calls replaced with `with open() as f:` in `gui_server.py`
- **Duplicate `ToolResult` import** — removed redundant `import ToolResult as TR` in `mahjong-industry-pack/main.py`
- **MCP stdio transport** — replaced `asyncio.get_running_loop()._stdin` with `sys.stdin.buffer`
- **14 unused imports** auto-fixed in `mcp/server.py` and `mcp/transport.py`

### Removed

- `openfang_cube/cube.md` from `plugins/` — moved to `docs/archive/` (LLM design document, not a plugin)
- `mahjong-industry-pack/legacy/` — 64 files of dead code, debug scripts, and stale tests archived

### Security

- BFF CORS restricted to configured origins (no more `allow_origins=["*"]`)
- RBAC enforcement available via `MORE_ENABLE_RBAC=1` environment variable

## [0.4.0] - 2026-05-10

### Added

- **Hands system** — autonomous agent packages with registry, manager, and browser hand
- **Skills module** — modular capabilities with web skills, code skills, and config injection
- **Commands registry** — unified slash command system with surface targeting
- **Cron scheduler** — scheduled task execution with parser, trigger, and manager
- **Workflows engine** — multi-step orchestration with dependency resolution
- **Deployments manager** — agent/service lifecycle management
- **Session management** — user access with subscription/topics
- **Hot-reload** — subsystem hot-reloading without restart
- **Reasoning router** — intelligent LLM selection based on reasoning capabilities
- **Model aliases** — standardized model name resolution across providers
- **Channel reconnect** — automatic reconnection with exponential backoff
- **Hand persistence & clone** — save/restore hand state and cloning
- **Plan system** — token prediction, plan coordination, monitoring, and workflow bridge
- **Output filter** — sensitive data redaction (API keys, emails, phone numbers)
- **Taint tracking** — input sanitization and trust propagation
- **ZEN rules** — code quality governance with violation tracking

### Fixed

- `datetime.now()` timezone awareness in API timestamps
- F-string logging anti-pattern replaced with lazy evaluation
- `RateLimiter.wait_for_token` timeout protection added
- `_task_store` concurrency considerations documented

## [0.3.0] - 2026-04-27

### Added

- **QNMing MoRE OS** brand unification across all modules
- Complete six-layer architecture (L0–L5) with async Protocol interfaces
- `DGMEngine` with `BenchmarkRunner` evaluation loop and `SQLiteEvolutionArchive`
- `MetacognitionService` (Calibrator + HyperAgent) for L5
- `OntologyEngine` with forward-chaining `RuleEngine` for L3
- `PluginManager` + `PluginBase` SDK with `scaffold_plugin()` utility
- `LLMManager` multi-provider routing with fallback chain (Ollama / LMStudio / OpenAI-compat)
- `LinuxSandbox` with cgroup v2 hardening + `SubprocessSandbox` cross-platform
- `EventBus` async pub/sub with strong task references
- `PolicyEnforcer` governance checks + `AuditLogger` JSONL audit trail
- `LayerRouter` difficulty-aware pipeline routing with feature gates
- SQLite persistent backends for memory and evolution archive
- FastAPI platform API (`/api/v1/*`) with health, tasks, plugins, ontology endpoints
- CLI entry points: `more-os serve` / `more-os run`
- 48 unit/integration tests (all passing)
- Mahjong Industry Pack (plugin case study, migrated from standalone MVP)
- Root-level `Makefile` with install/test/lint/serve/build/clean commands
- `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE` (Apache-2.0)
- Environment check script (`make check-env`)

### Fixed

- `SQLiteEvolutionArchive.update()` now persists `performance`/`verified` changes
- `PluginBase.CAPABILITIES`/`DEPENDENCIES` changed from mutable `[]` to immutable `()`
- `LinuxSandbox` cgroup setup failures now logged instead of silently swallowed
- `EventBus` tasks kept alive via `_pending_tasks` set (prevents GC warnings)
- `EventBus._safe_call` logs handler exceptions at debug level
- Unused imports removed (`Deque` in sqlite_store, `ToolRegistry` in builtins)
- `orchestrator.py` import ordering normalized; `os` moved to top-level
- `SQLiteEvolutionArchive` now exported from `evolution/__init__.py`
- `MoRECore.stop()` closes SQLite connections for memory and evolution backends
- `CODE_DEBUGGING`/`CODE_REVIEW` pipelines corrected (L2→L1)
- `conftest.py` core fixture return type fixed to `AsyncGenerator`
- `benchmark.py` `asyncio.gather` explicitly sets `return_exceptions=False`
- `pyproject.toml` version reads dynamically from `version.py` (single source)
- `l5_metacognition.py` alignment value explicitly cast to `float()`
- `l0_execution.py` `_extract_python` made case-insensitive + supports `` ```py ``
- `api/server.py` `target_layer` string correctly converted to `LayerId` enum
- `sqlite_store.py` search `access_count` batch-updated in single SQL statement

## [0.2.0] - 2026-04-26

### Added

- Initial `more_core` package extracted from MVP
- Basic L0–L5 layer stubs
- MVP frontend (`app/`) with React + Vite

## [0.1.0] - 2026-04-24

### Added

- Mahjong MVP concept validation
- Initial LLM integration (Ollama/LMStudio)
