#!/usr/bin/env bash
# ============================================================
# QNMing MoRE OS — One-Command Full Stack Installer
# ============================================================
# Usage:
#   bash install.sh              # check environment only
#   bash install.sh --install    # full install
#   bash install.sh --upgrade    # reinstall / upgrade
#   bash install.sh --dev        # install with dev deps
#   bash install.sh --verify     # verify installation
#   bash install.sh --uninstall  # remove .venv + node_modules
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; NC='\033[0m'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"

PASS=0; FAIL=0; WARN=0

ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; WARN=$((WARN + 1)); }

# Detect version from source
MORE_VERSION="$(grep '__version__' "$ROOT_DIR/more_core/more_core/version.py" 2>/dev/null | sed "s/.*= \"//;s/\"//" || echo "0.0.0")"

# ============================================================
# OS detection
detect_os() {
    case "$(uname -s)" in
        Darwin*)  echo "macos" ;;
        Linux*)   echo "linux" ;;
        *)        echo "unknown" ;;
    esac
}

# ============================================================
# Prerequisite checks
check_python() {
    echo -e "\n${CYAN}── Python${NC}"
    if command -v python3 &>/dev/null; then
        VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        MAJ=$(echo "$VER" | cut -d. -f1); MIN=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJ" -ge 3 ] && [ "$MIN" -ge 10 ]; then
            ok "Python $VER (>= 3.10)"
        else
            fail "Python $VER (need >= 3.10)"
        fi
    else
        fail "python3 not found — install from https://python.org"
    fi
}

check_node() {
    echo -e "\n${CYAN}── Node.js (optional, for Dashboard)${NC}"
    if command -v node &>/dev/null; then
        NVER=$(node --version | sed 's/v//')
        NMAJ=$(echo "$NVER" | cut -d. -f1)
        if [ "$NMAJ" -ge 18 ]; then
            ok "Node.js $NVER"
        else
            warn "Node.js $NVER (need >= 18)"
        fi
    else
        warn "not installed — Dashboard won't be available"
    fi
}

check_make() {
    echo -e "\n${CYAN}── Make${NC}"
    if command -v make &>/dev/null; then
        ok "$(make --version 2>&1 | head -1)"
    else
        warn "make not found — use 'brew install make' (macOS) or 'apt install build-essential' (Linux)"
    fi
}

check_lmstudio() {
    echo -e "\n${CYAN}── LM Studio (primary LLM provider)${NC}"
    if curl -s --max-time 2 http://localhost:1234/v1/models >/dev/null 2>&1; then
        ok "Running on port 1234"
    else
        warn "Not running — install from https://lmstudio.ai"
    fi
}

check_ollama() {
    echo -e "\n${CYAN}── Ollama (fallback LLM)${NC}"
    if curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
        ok "Running on port 11434"
    else
        warn "Not running — install: brew install ollama && ollama serve"
    fi
}

check_git() {
    echo -e "\n${CYAN}── Git${NC}"
    if command -v git &>/dev/null; then
        ok "$(git --version)"
    else
        fail "git not found"
    fi
}

# ============================================================
do_install() {
    local dev="${1:-false}"
    local upgrade="${2:-false}"

    echo -e "\n${GREEN}==============================================${NC}"
    echo -e "${GREEN}  Installing QNMing MoRE OS v${MORE_VERSION}${NC}"
    echo -e "${GREEN}==============================================${NC}"

    VENV_DIR="$ROOT_DIR/.venv"

    # 1. Virtual environment
    if $upgrade && [ -d "$VENV_DIR" ]; then
        echo -e "\n${YELLOW}[1/4] Removing existing virtual environment...${NC}"
        rm -rf "$VENV_DIR"
        ok ".venv removed for upgrade"
    fi

    if [ ! -d "$VENV_DIR" ]; then
        echo -e "\n${CYAN}[1/4] Creating virtual environment...${NC}"
        python3 -m venv "$VENV_DIR"
        ok ".venv created"
    else
        ok ".venv already exists"
    fi

    # 2. Python dependencies
    echo -e "\n${CYAN}[2/4] Installing Python dependencies...${NC}"
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    if $dev; then
        "$VENV_DIR/bin/pip" install -e "$ROOT_DIR/more_core[all]" -q
        ok "Python packages installed (with dev dependencies)"
    else
        "$VENV_DIR/bin/pip" install -e "$ROOT_DIR/more_core[api]" -q
        ok "Python packages installed (API runtime)"
    fi

    # 3. Frontend dependencies
    if command -v node &>/dev/null; then
        echo -e "\n${CYAN}[3/4] Installing frontend dependencies...${NC}"
        if $upgrade && [ -d "$ROOT_DIR/app/node_modules" ]; then
            rm -rf "$ROOT_DIR/app/node_modules"
        fi
        cd "$ROOT_DIR/app" && npm install --silent 2>/dev/null
        ok "Frontend packages installed"
        cd "$ROOT_DIR"
    else
        warn "[3/4] Skipped frontend — Node.js not found"
    fi

    # 4. Environment configuration
    echo -e "\n${CYAN}[4/4] Setting up environment...${NC}"
    if [ ! -f "$ROOT_DIR/more_core/.env" ]; then
        if [ -f "$ROOT_DIR/more_core/.env.template" ]; then
            cp "$ROOT_DIR/more_core/.env.template" "$ROOT_DIR/more_core/.env"
            ok ".env created from template"
        else
            {
                echo "# QNMing MoRE OS — Environment Configuration"
                echo "MORE_LMSTUDIO_ENDPOINT=http://localhost:1234/v1"
                echo "MORE_OLLAMA_ENDPOINT=http://localhost:11434"
                echo "MORE_LLM_FALLBACK_CHAIN=lmstudio,ollama"
                echo "MORE_ENABLE_SYMBOLIC=1"
                echo "MORE_ENABLE_EVOLUTION=0"
                echo "MORE_ENABLE_METACOGNITION=0"
            } > "$ROOT_DIR/more_core/.env"
            ok ".env created with defaults"
        fi
    else
        ok ".env already exists"
    fi

    # Frontend .env
    if [ ! -f "$ROOT_DIR/app/.env" ]; then
        echo "VITE_API_BASE=http://localhost:8011" > "$ROOT_DIR/app/.env"
        ok "app/.env created"
    else
        ok "app/.env already exists"
    fi

    # Create data directories
    mkdir -p "$ROOT_DIR/data" "$ROOT_DIR/logs" 2>/dev/null || true

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  Installation complete! v${MORE_VERSION}          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Quick start:"
    echo "  source .venv/bin/activate"
    echo "  make serve          # start API (foreground, port 8011)"
    echo ""
    echo "Or in background:"
    echo "  make start          # start API (background)"
    echo "  make serve-app      # start frontend (separate terminal)"
    echo ""
    echo "Verify:"
    echo "  make health         # curl API /health"
    echo "  bash install.sh --verify"
}

# ============================================================
do_verify() {
    echo -e "\n${GREEN}── Verifying Installation${NC}"

    if [ -d "$ROOT_DIR/.venv" ] && "$ROOT_DIR/.venv/bin/python" -c "import more_core; print(more_core.__version__)" 2>/dev/null; then
        VER=$("$ROOT_DIR/.venv/bin/python" -c "import more_core; print(more_core.__version__)")
        ok "more_core v$VER importable"
    else
        fail "more_core not importable — run: bash install.sh --install"
    fi

    if curl -s --max-time 3 http://localhost:8011/api/v1/health >/dev/null 2>&1; then
        ok "API running on port 8011"
    else
        warn "API not running on port 8011"
    fi

    if curl -s --max-time 3 http://localhost:3003 >/dev/null 2>&1; then
        ok "Dashboard serving on port 3003"
    else
        warn "Dashboard not running on port 3003"
    fi

    echo ""
    echo -e "Results: ${GREEN}$PASS passed${NC}, ${YELLOW}$WARN warnings${NC}, ${RED}$FAIL failed${NC}"
}

# ============================================================
do_uninstall() {
    echo -e "\n${YELLOW}── Uninstalling QNMing MoRE OS${NC}"
    
    local removed=false
    
    if [ -d "$ROOT_DIR/.venv" ]; then
        rm -rf "$ROOT_DIR/.venv"
        ok ".venv removed"
        removed=true
    fi
    
    if [ -d "$ROOT_DIR/app/node_modules" ]; then
        rm -rf "$ROOT_DIR/app/node_modules"
        ok "app/node_modules removed"
        removed=true
    fi

    if [ -f "$ROOT_DIR/more_core/.env" ]; then
        rm -f "$ROOT_DIR/more_core/.env"
        ok "more_core/.env removed"
        removed=true
    fi

    if [ -f "$ROOT_DIR/app/.env" ]; then
        rm -f "$ROOT_DIR/app/.env"
        ok "app/.env removed"
        removed=true
    fi

    if ! $removed; then
        warn "Nothing to uninstall"
    fi
    
    echo ""
    echo "To remove data files: rm -rf data/ logs/"
}

# ============================================================
# Main
# ============================================================

echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  QNMing MoRE OS v${MORE_VERSION} — Environment Setup  ${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"

check_python
check_node
check_make
check_git
check_lmstudio
check_ollama

echo ""
echo -e "Results: ${GREEN}$PASS passed${NC}, ${YELLOW}$WARN warnings${NC}, ${RED}$FAIL failed${NC}"

case "${1:-}" in
    --install|-i)
        [ $FAIL -gt 0 ] && { echo -e "\n${RED}Cannot install: $FAIL prerequisite(s) missing${NC}"; exit 1; }
        do_install false false
        do_verify
        ;;
    --dev|-d)
        [ $FAIL -gt 0 ] && { echo -e "\n${RED}Cannot install: $FAIL prerequisite(s) missing${NC}"; exit 1; }
        do_install true false
        do_verify
        ;;
    --upgrade|-u)
        do_install true true
        do_verify
        ;;
    --verify|-v)
        do_verify
        ;;
    --uninstall)
        do_uninstall
        ;;
    *)
        echo ""
        echo "Commands:"
        echo "  bash install.sh --install    # full install (runtime)"
        echo "  bash install.sh --dev        # install with dev dependencies"
        echo "  bash install.sh --upgrade    # reinstall / upgrade"
        echo "  bash install.sh --verify     # verify installation"
        echo "  bash install.sh --uninstall  # remove .venv + node_modules"
        ;;
esac

exit $FAIL
