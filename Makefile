# ============================================================
# QNMing MoRE OS — Development & Operations Makefile
# ============================================================
# Version: 0.8.0
# ============================================================

.PHONY: help setup install install-dev install-app install-all \
        start stop restart status health \
        serve serve-app build build-app test lint format typecheck \
        check clean check-env setup-hooks docker-build docker-up docker-down

PYTHON  ?= $(CURDIR)/.venv/bin/python
PIP     ?= $(CURDIR)/.venv/bin/pip
API_PORT ?= 8011
APP_PORT ?= 3003

# ============================================================
# Help
# ============================================================

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ============================================================
# Setup & Installation
# ============================================================

setup: ## One-command setup: check env + install + init
	@bash install.sh --dev

install: ## Install more_core with API support
	cd more_core && $(PIP) install -e ".[api]"

install-dev: ## Install more_core with all dev dependencies
	cd more_core && $(PIP) install -e ".[all]"

install-app: ## Install frontend dependencies
	cd app && npm install

install-all: ## Install everything (Python dev + frontend)
	cd more_core && $(PIP) install -e ".[all]"
	cd app && npm install

# ============================================================
# Service Lifecycle
# ============================================================

start: ## Start API server (background, port $(API_PORT))
	@echo "Starting MoRE OS API on port $(API_PORT)..."
	@nohup $(PYTHON) -m more_core.cli serve --host 0.0.0.0 --port $(API_PORT) \
		> /tmp/more-os-api.log 2>&1 &
	@sleep 2
	@$(PYTHON) -c "import httpx; r=httpx.get('http://localhost:$(API_PORT)/api/v1/health', timeout=3); print(r.json()['status'])"

stop: ## Stop API server
	@echo "Stopping MoRE OS API..."
	@pkill -f "more_core.cli serve" 2>/dev/null || true
	@pkill -f "uvicorn" 2>/dev/null || true
	@echo "Done."

restart: stop start ## Restart API server

status: ## Show running MoRE OS processes
	@echo "=== MoRE OS Processes ==="
	@pgrep -fl "more_core" || echo "  (none)"
	@echo ""
	@echo "=== Port Usage ==="
	@lsof -i :$(API_PORT) -i :$(APP_PORT) 2>/dev/null | grep LISTEN || echo "  (no services listening)"

health: ## Quick health check (honours MORE_API_KEY / more_core/.env)
	@$(PYTHON) -c "import os,httpx,pathlib;\
key=os.getenv('MORE_API_KEY','');\
key=key or next((l.split('=',1)[1].strip().strip('\"') for l in pathlib.Path('more_core/.env').read_text().splitlines() if l.startswith('MORE_API_KEY=')), '') if pathlib.Path('more_core/.env').exists() else '';\
h={'Authorization':'Bearer '+key} if key else {};\
r=httpx.get('http://localhost:$(API_PORT)/api/v1/health', headers=h, timeout=5);\
print(r.json())" 2>/dev/null \
		|| echo "API unreachable or unauthorized on port $(API_PORT)"

# ============================================================
# Run (foreground)
# ============================================================

serve: ## Start API server (foreground, port $(API_PORT))
	@cd more_core && $(PYTHON) -m more_core.cli serve --host 0.0.0.0 --port $(API_PORT)

serve-app: ## Start frontend dev server (foreground, port $(APP_PORT))
	@cd app && npm run dev

serve-all: ## Start both API + frontend (requires tmux or two terminals)
	@echo "Run in separate terminals:"
	@echo "  make serve"
	@echo "  make serve-app"

# ============================================================
# Build & Package
# ============================================================

build: ## Build Python package (sdist + wheel)
	@cd more_core && $(PYTHON) -m build

build-app: ## Build frontend for production
	@cd app && npm run build

# ============================================================
# Testing
# ============================================================

test: ## Run Python test suite
	@cd more_core && $(PYTHON) -m pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage (enforced gate)
	@cd more_core && $(PYTHON) -m pytest tests/ -v --tb=short \
		--cov=more_core --cov-report=term-missing --cov-fail-under=50

test-app: ## Run frontend tests
	@cd app && npm test

# ============================================================
# Code Quality
# ============================================================

lint: ## Run ruff linter on Python code
	@cd more_core && $(PYTHON) -m ruff check more_core/ tests/

format: ## Auto-format with ruff
	@cd more_core && $(PYTHON) -m ruff format more_core/ tests/

typecheck: ## Run mypy type checker
	@cd more_core && $(PYTHON) -m mypy more_core/ || true

check: lint typecheck test ## Run all quality checks (lint + typecheck + test)

# ============================================================
# Clean
# ============================================================

clean: ## Remove build artifacts and caches
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	@rm -rf more_core/build more_core/dist
	@rm -f /tmp/more-os-api.log /tmp/more-os-frontend.log
	@echo "Cleaned."

clean-all: clean ## Deep clean: remove .venv + node_modules
	@rm -rf .venv app/node_modules
	@echo "Deep cleaned: .venv and node_modules removed."

# ============================================================
# Environment Check
# ============================================================

check-env: ## Verify development environment
	@echo "=== QNMing MoRE OS — Environment Check ==="
	@echo -n "Python:  " && $(PYTHON) --version 2>/dev/null || echo "NOT FOUND"
	@echo -n "pip:     " && $(PIP) --version 2>/dev/null || echo "NOT FOUND"
	@echo -n "node:    " && node --version 2>/dev/null || echo "NOT FOUND (optional)"
	@echo -n "npm:     " && npm --version 2>/dev/null || echo "NOT FOUND (optional)"
	@echo -n "LMStudio:" && (curl -s --max-time 2 http://localhost:1234/v1/models >/dev/null 2>&1 && echo "RUNNING" || echo "OFFLINE")
	@echo -n "Ollama:  " && (curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 && echo "RUNNING" || echo "OFFLINE")
	@echo "==========================================="

# ============================================================
# Docker
# ============================================================

docker-build: ## Build Docker image
	@docker build -t qnming-more-os:latest .

docker-up: ## Start with docker-compose
	@docker-compose up -d

docker-down: ## Stop docker-compose
	@docker-compose down

# ============================================================
# Git Hooks
# ============================================================

setup-hooks: ## Install pre-commit hook (runs lint-check on commit)
	@echo "Installing pre-commit hook..."
	@mkdir -p .git/hooks
	@printf '#!/bin/sh\nmake check\n' > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hook installed."
