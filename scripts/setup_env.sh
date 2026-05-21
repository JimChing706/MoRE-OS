#!/usr/bin/env bash
# ============================================================
# QNMing MoRE OS — Environment Setup & Verification Script
# ============================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=============================================="
echo "  QNMing MoRE OS — Environment Setup v0.3.0"
echo "=============================================="
echo ""

ERRORS=0

# --- Python check ---
echo -n "Checking Python 3.10+ ... "
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        echo -e "${GREEN}OK${NC} (Python $PY_VER)"
    else
        echo -e "${RED}FAIL${NC} (Python $PY_VER < 3.10)"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS=$((ERRORS + 1))
fi

# --- pip check ---
echo -n "Checking pip ... "
if command -v pip &>/dev/null || command -v pip3 &>/dev/null; then
    PIP_VER=$(pip3 --version 2>/dev/null || pip --version 2>/dev/null)
    echo -e "${GREEN}OK${NC} ($PIP_VER)"
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS=$((ERRORS + 1))
fi

# --- Node.js check (optional) ---
echo -n "Checking Node.js 18+ (optional, for Dashboard) ... "
if command -v node &>/dev/null; then
    NODE_VER=$(node --version | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        echo -e "${GREEN}OK${NC} (Node $NODE_VER)"
    else
        echo -e "${YELLOW}WARN${NC} (Node $NODE_VER < 18)"
    fi
else
    echo -e "${YELLOW}SKIP${NC} (not installed, Dashboard won't work)"
fi

# --- Git check ---
echo -n "Checking Git ... "
if command -v git &>/dev/null; then
    GIT_VER=$(git --version)
    echo -e "${GREEN}OK${NC} ($GIT_VER)"
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# --- Virtual environment ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ "$1" = "--install" ]; then
    echo "----------------------------------------------"
    echo "  Installing QNMing MoRE OS ..."
    echo "----------------------------------------------"

    # Create venv if not exists
    if [ ! -d "$ROOT_DIR/.venv" ]; then
        echo "Creating virtual environment at $ROOT_DIR/.venv ..."
        python3 -m venv "$ROOT_DIR/.venv"
    fi

    echo "Activating virtual environment ..."
    source "$ROOT_DIR/.venv/bin/activate"

    echo "Installing more_core with all extras ..."
    pip install -e "$ROOT_DIR/more_core[all]"

    echo ""
    echo -e "${GREEN}Installation complete!${NC}"
    echo ""
    echo "To activate the environment:"
    echo "  source $ROOT_DIR/.venv/bin/activate"
    echo ""
    echo "To start the API server:"
    echo "  more-os serve --port 8001"
    echo ""
    echo "To run tests:"
    echo "  cd $ROOT_DIR/more_core && python3 -m pytest tests/ -v"
fi

# --- Summary ---
echo ""
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}Environment check found $ERRORS error(s). Please fix before proceeding.${NC}"
    exit 1
else
    echo -e "${GREEN}Environment check passed!${NC}"
    if [ "$1" != "--install" ]; then
        echo ""
        echo "Run with --install to set up the environment:"
        echo "  bash scripts/setup_env.sh --install"
    fi
    exit 0
fi
