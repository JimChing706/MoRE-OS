# ============================================================
# QNMing MoRE OS — Development Makefile
# ============================================================

.PHONY: help install install-dev test lint serve clean docs

PYTHON ?= python3
PIP    ?= pip

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---- Installation ----

install: ## Install more_core with API support
	cd more_core && $(PIP) install -e ".[api]"

install-dev: ## Install more_core with all dev dependencies
	cd more_core && $(PIP) install -e ".[all]"

install-app: ## Install frontend dependencies
	cd app && npm install

install-all: install-dev install-app ## Install everything

# ---- Testing ----

test: ## Run Python test suite
	cd more_core && $(PYTHON) -m pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage
	cd more_core && $(PYTHON) -m pytest tests/ -v --tb=short --cov=more_core --cov-report=term-missing

# ---- Code Quality ----

lint: ## Run ruff linter
	cd more_core && $(PYTHON) -m ruff check more_core/ tests/

format: ## Auto-format with ruff
	cd more_core && $(PYTHON) -m ruff format more_core/ tests/

typecheck: ## Run mypy type checker
	cd more_core && $(PYTHON) -m mypy more_core/

# ---- Run ----

serve: ## Start the MoRE OS API server (port 8001)
	cd more_core && $(PYTHON) -m more_core.cli serve --host 0.0.0.0 --port 8001

serve-app: ## Start the frontend dev server
	cd app && npm run dev

# ---- Build & Package ----

build: ## Build Python package
	cd more_core && $(PYTHON) -m build

build-app: ## Build frontend for production
	cd app && npm run build

# ---- Clean ----

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf more_core/build more_core/dist

# ---- Environment Check ----

check-env: ## Verify development environment
	@echo "=== QNMing MoRE OS — Environment Check ==="
	@echo -n "Python: " && $(PYTHON) --version 2>&1 || echo "NOT FOUND"
	@echo -n "pip:    " && $(PIP) --version 2>&1 || echo "NOT FOUND"
	@echo -n "node:   " && node --version 2>&1 || echo "NOT FOUND (optional, for app/)"
	@echo -n "npm:    " && npm --version 2>&1 || echo "NOT FOUND (optional, for app/)"
	@echo -n "git:    " && git --version 2>&1 || echo "NOT FOUND"
	@echo "==========================================="
