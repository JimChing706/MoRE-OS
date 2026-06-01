# QNMing MoRE OS — Installation Guide

> v0.6.0-alpha · macOS / Linux · Python 3.10+ · Node.js 18+ (optional)

---

## Quick Start (3 commands)

```bash
# 1. Check prerequisites
python3 --version          # >= 3.10
node --version             # >= 18 (optional, for Dashboard)

# 2. One-command install
bash install.sh --install

# 3. Start services
make start                 # API on http://localhost:8011
cd app && npm run dev      # Dashboard on http://localhost:3003 (separate terminal)
```

**Verify**: `bash scripts/health_check.sh`

---

## Prerequisites

| Component | Min Version | Required | Install |
|-----------|-------------|----------|---------|
| Python | 3.10 | Yes | https://python.org or `brew install python@3.14` |
| Node.js | 18 | No* | https://nodejs.org or `brew install node` |
| LM Studio | latest | No** | https://lmstudio.ai |
| Ollama | latest | No** | `brew install ollama && ollama serve` |

\* Required for Dashboard (React frontend). API-only deployment skips Node.js.
\** At least one LLM provider must be running for task execution.

---

## Installation Steps

### Step 1: Clone & Enter

```bash
cd /path/to/qnm-os-prev-202605211332
```

### Step 2: Environment Check

```bash
bash install.sh
```

Output shows which prerequisites are met.

### Step 3: Install

```bash
bash install.sh --install
```

This performs:
1. Creates `.venv/` virtual environment (Python 3.10+)
2. Installs `more_core[all]` (API + dev + optional deps)
3. Installs `app/` npm dependencies
4. Creates `more_core/.env` from `.env.template`
5. Creates `app/.env` with `VITE_API_BASE=http://localhost:8011`

### Step 4: Configure LLM Provider

Edit `more_core/.env`:

```bash
# Primary: LM Studio
MORE_LMSTUDIO_ENDPOINT=http://localhost:1234/v1
MORE_LMSTUDIO_MODEL=your-model-name

# Fallback: Ollama
MORE_OLLAMA_ENDPOINT=http://localhost:11434
MORE_OLLAMA_MODEL=qwen2.5:7b

# Fallback chain (tried in order)
MORE_LLM_FALLBACK_CHAIN=lmstudio,ollama
```

### Step 5: Start Services

```bash
# Option A: Makefile (background)
make start && make health

# Option B: Foreground
make serve

# Option C: Launcher
./run-local-ai.sh start
```

---

## Service Management

### Makefile Targets

```bash
make start       # Start API (background)
make stop        # Stop API
make restart     # Stop + Start
make status      # Running processes + ports
make health      # API health check
make serve       # Start API (foreground)
make serve-app   # Start Dashboard (foreground)

make test        # Run Python test suite
make lint        # Ruff linter
make format      # Ruff formatter
make typecheck   # Mypy type check
make clean       # Remove artifacts
```

### Launcher Script

```bash
./run-local-ai.sh              # Interactive menu
./run-local-ai.sh start        # Start all services
./run-local-ai.sh stop         # Stop all services
./run-local-ai.sh status       # Service status
./run-local-ai.sh health       # Full health check
./run-local-ai.sh chat         # Local LLM chat
./run-local-ai.sh models       # List available models
```

### Health Check

```bash
bash scripts/health_check.sh
```

Checks: API health · LLM providers · Frontend · Databases · Plugins

---

## Port Map

| Service | Port | URL |
|---------|------|-----|
| MoRE OS API | 8011 | http://localhost:8011 |
| API Docs (Swagger) | 8011 | http://localhost:8011/docs |
| Dashboard (Vite) | 3003 | http://localhost:3003 |
| LM Studio | 1234 | http://localhost:1234 |
| Ollama | 11434 | http://localhost:11434 |

---

## Environment Variables

Full reference: `more_core/.env.template`

### Required

```bash
MORE_LMSTUDIO_ENDPOINT=http://localhost:1234/v1
MORE_OLLAMA_ENDPOINT=http://localhost:11434
MORE_LLM_FALLBACK_CHAIN=lmstudio,ollama
```

### Feature Gates

```bash
MORE_ENABLE_SYMBOLIC=1       # Symbolic reasoning (L3)
MORE_ENABLE_EVOLUTION=1      # Neuro-evolution (L2)
MORE_ENABLE_METACOGNITION=1  # Metacognition (L5)
```

### Optional

```bash
MORE_MEMORY_DB=data/memory.db
MORE_EVOLUTION_DB=data/evolution.db
MORE_CORS_ORIGINS=http://localhost:3000,http://localhost:3003
```

---

## Troubleshooting

**API won't start**: Check `lsof -i :8011` for port conflicts. Kill existing: `make stop`

**LM Studio offline**: Open LM Studio app, load a model, verify: `curl localhost:1234/v1/models`

**Dashboard "Failed to fetch"**: Verify `app/.env` has `VITE_API_BASE=http://localhost:8011`. Restart: `cd app && npm run dev`

**Ollama not responding**: Run `ollama serve` in a separate terminal. Pull model: `ollama pull qwen2.5:7b`

---

## Directory Layout

```
qnm-os-prev/
├── install.sh               # One-command installer
├── run-local-ai.sh          # Service launcher
├── Makefile                 # Dev/Ops targets
├── more_core/               # Python package
│   ├── .env.template        # Env template
│   ├── .env                 # Active config
│   ├── pyproject.toml       # Package def
│   └── more_core/           # Source
├── app/                     # React frontend
│   ├── .env                 # VITE_API_BASE
│   └── src/                 # Source
├── plugins/                 # Industry plugins
├── scripts/                 # Utility scripts
│   ├── health_check.sh      # Stack health
│   ├── setup_env.sh         # Legacy env setup
│   └── ...
├── docs/                    # Documentation
│   ├── INSTALL.md           # This file
│   ├── OPERATION_MANUAL.md  # Full manual
│   └── adr/                 # Architecture decisions
└── data/                    # Runtime databases
```

---

## Upgrading

```bash
git pull
make install-all            # Reinstall deps
make restart                # Restart API
```
