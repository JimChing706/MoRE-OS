# ============================================================
# QNMing MoRE OS — Development & Operations Makefile
# ============================================================

.PHONY: help install install-dev install-app install-all \
        start stop restart status health \
        serve serve-app build build-app test lint clean check-env

PYTHON  ?= .venv/bin/python
PIP     ?= .venv/bin/pip
API_PORT ?= 8011

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ============================================================
# Installation
# ============================================================

install: ## Install more_core with API support
	cd more_core && $(PIP) install -e ".[api]"

install-dev: ## Install more_core with all dev dependencies
	cd more_core && $(PIP) install -e ".[all]"

install-app: ## Install frontend dependencies
	cd app && npm install

install-all: install-dev install-app ## Install everything (Python + JS)

# ============================================================
# Service Lifecycle
# ============================================================

start: ## Start API server (background)
	@echo "Starting MoRE OS API on port $(API_PORT)..."
	@nohup $(PYTHON) -m more_core.cli serve --host 0.0.0.0 --port $(API_PORT) \
		> /tmp/more-os-api.log 2>&1 &
	@sleep 2
	@$(PYTHON) -c "import httpx; r=httpx.get('http://localhost:$(API_PORT)/api/v1/health', timeout=3); print(r.json()['status'])"

stop: ## Stop API server
	@echo "Stopping MoRE OS API..."
	@pkill -f "more_core.cli serve" 2>/dev/null || true
	@echo "Done."

restart: stop start ## Restart API server

status: ## Show running MoRE OS processes
	@echo "=== MoRE OS Processes ==="
	@pgrep -fl "more_core" || echo "  (none)"
	@echo ""
	@echo "=== Port Usage ==="
	@lsof -i :$(API_PORT) -i :3002 -i :3003 2>/dev/null | grep LISTEN || echo "  (no services listening)"

health: ## Quick health check
	@curl -s http://localhost:$(API_PORT)/api/v1/health | $(PYTHON) -m json.tool || echo "API unreachable"

# ============================================================
# Run (foreground)
# ============================================================

serve: ## Start MoRE OS API server (foreground, port $(API_PORT))
	cd more_core && $(PYTHON) -m more_core.cli serve --host 0.0.0.0 --port $(API_PORT)

serve-app: ## Start frontend dev server (foreground, port 3002+)
	cd app && npm run dev

# ============================================================
# Build & Package
# ============================================================

build: ## Build Python package
	cd more_core && $(PYTHON) -m build

build-app: ## Build frontend for production
	cd app && npm run build

# ============================================================
# Testing
# ============================================================

test: ## Run Python test suite
	cd more_core && $(PYTHON) -m pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage
	cd more_core && $(PYTHON) -m pytest tests/ -v --tb=short \
		--cov=more_core --cov-report=term-missing

# ============================================================
# Code Quality
# ============================================================

lint: ## Run ruff linter
	cd more_core && $(PYTHON) -m ruff check more_core/ tests/

format: ## Auto-format with ruff
	cd more_core && $(PYTHON) -m ruff format more_core/ tests/

typecheck: ## Run mypy type checker
	cd more_core && $(PYTHON) -m mypy more_core/

# ============================================================
# Clean
# ============================================================

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf more_core/build more_core/dist
	rm -f /tmp/more-os-api.log /tmp/more-os-frontend.log

# ============================================================
# Environment Check
# ============================================================

check-env: ## Verify development environment
	@echo "=== QNMing MoRE OS — Environment Check ==="
	@echo -n "Python:  " && $(PYTHON) --version 2>/dev/null || echo "NOT FOUND"
	@echo -n "pip:     " && $(PIP) --version 2>/dev/null || echo "NOT FOUND"
	@echo -n "node:    " && node --version 2>/dev/null || echo "NOT FOUND (optional, for app/)"
	@echo -n "npm:     " && npm --version 2>/dev/null || echo "NOT FOUND (optional, for app/)"
	@echo -n "LMStudio:" && (curl -s --max-time 2 http://localhost:1234/v1/models >/dev/null 2>&1 && echo "RUNNING" || echo "OFFLINE")
	@echo -n "Ollama:  " && (curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 && echo "RUNNING" || echo "OFFLINE")
	@echo "==========================================="
