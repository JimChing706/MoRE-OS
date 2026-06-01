#!/usr/bin/env bash
# ============================================================
# QNMing MoRE OS — One-Command Full Stack Install
# ============================================================
# Usage:
#   bash install.sh              # check environment only
#   bash install.sh --install    # full install (venv + pip + npm + .env)
#   bash install.sh --verify     # verify installation
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"

PASS=0; FAIL=0; WARN=0

ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; WARN=$((WARN + 1)); }

# ============================================================
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

check_lmstudio() {
    echo -e "\n${CYAN}── LM Studio (LLM provider)${NC}"
    if curl -s --max-time 2 http://localhost:1234/v1/models >/dev/null 2>&1; then
        COUNT=$(curl -s http://localhost:1234/v1/models | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo "?")
        ok "Running — $COUNT model(s) loaded"
    else
        warn "Not running — install from https://lmstudio.ai"
    fi
}

check_ollama() {
    echo -e "\n${CYAN}── Ollama (fallback LLM)${NC}"
    if curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
        COUNT=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
        ok "Running — $COUNT model(s) loaded"
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
    echo -e "\n${GREEN}==============================================${NC}"
    echo -e "${GREEN}  Installing QNMing MoRE OS v0.6.0${NC}"
    echo -e "${GREEN}==============================================${NC}"

    # 1. Virtual environment
    if [ ! -d "$ROOT_DIR/.venv" ]; then
        echo -e "\n${CYAN}[1/4] Creating virtual environment...${NC}"
        python3 -m venv "$ROOT_DIR/.venv"
        ok ".venv created"
    else
        ok ".venv already exists"
    fi

    # 2. Python dependencies
    echo -e "\n${CYAN}[2/4] Installing Python dependencies...${NC}"
    "$ROOT_DIR/.venv/bin/pip" install --upgrade pip -q
    "$ROOT_DIR/.venv/bin/pip" install -e "$ROOT_DIR/more_core[all]" -q
    ok "Python packages installed"

    # 3. Frontend dependencies
    if command -v node &>/dev/null; then
        echo -e "\n${CYAN}[3/4] Installing frontend dependencies...${NC}"
        cd "$ROOT_DIR/app" && npm install --silent
        ok "Frontend packages installed"
    else
        warn "[3/4] Skipped frontend — Node.js not found"
    fi

    # 4. Environment config
    echo -e "\n${CYAN}[4/4] Setting up environment...${NC}"
    if [ ! -f "$ROOT_DIR/more_core/.env" ]; then
        if [ -f "$ROOT_DIR/more_core/.env.template" ]; then
            cp "$ROOT_DIR/more_core/.env.template" "$ROOT_DIR/more_core/.env"
            ok ".env created from template"
        else
            echo "# QNMing MoRE OS — Environment Configuration" > "$ROOT_DIR/more_core/.env"
            echo "MORE_LMSTUDIO_ENDPOINT=http://localhost:1234/v1" >> "$ROOT_DIR/more_core/.env"
            echo "MORE_OLLAMA_ENDPOINT=http://localhost:11434" >> "$ROOT_DIR/more_core/.env"
            echo "MORE_LLM_FALLBACK_CHAIN=lmstudio,ollama" >> "$ROOT_DIR/more_core/.env"
            echo "MORE_ENABLE_SYMBOLIC=1" >> "$ROOT_DIR/more_core/.env"
            echo "MORE_ENABLE_EVOLUTION=1" >> "$ROOT_DIR/more_core/.env"
            echo "MORE_ENABLE_METACOGNITION=1" >> "$ROOT_DIR/more_core/.env"
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

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  安装完成!                                    ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo "启动 MoRE OS:"
    echo "  make start                    # 后台启动 API"
    echo "  make serve-app                # 启动前端 (另一个终端)"
    echo ""
    echo "或手动:"
    echo "  .venv/bin/python -m more_core.cli serve --host 0.0.0.0 --port 8011"
    echo "  cd app && npm run dev"
    echo ""
    echo "健康检查:"
    echo "  bash scripts/health_check.sh"
    echo "  make health"
}

# ============================================================
do_verify() {
    echo -e "\n${GREEN}── Verifying Installation${NC}"

    # Check .venv
    if [ -d "$ROOT_DIR/.venv" ] && "$ROOT_DIR/.venv/bin/python" -c "import more_core" 2>/dev/null; then
        ok "more_core importable"
    else
        fail "more_core not importable — run: make install-dev"
    fi

    # Check API
    if curl -s --max-time 3 http://localhost:8011/api/v1/health >/dev/null 2>&1; then
        ok "API healthy (port 8011)"
    else
        warn "API not running on port 8011"
    fi

    # Check frontend
    if curl -s --max-time 3 http://localhost:3003 >/dev/null 2>&1; then
        ok "Frontend serving (port 3003)"
    else
        warn "Frontend not running on port 3003"
    fi
}

# ============================================================
# Main
# ============================================================

echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  QNMing MoRE OS — Environment Setup          ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"

check_python
check_node
check_git
check_lmstudio
check_ollama

echo ""
echo -e "Results: ${GREEN}$PASS passed${NC}, ${YELLOW}$WARN warnings${NC}, ${RED}$FAIL failed${NC}"

case "${1:-}" in
    --install|-i)
        if [ $FAIL -gt 0 ]; then
            echo -e "\n${RED}Cannot install: $FAIL prerequisite(s) missing${NC}"
            exit 1
        fi
        do_install
        do_verify
        ;;
    --verify|-v)
        do_verify
        ;;
    *)
        echo ""
        echo "Run with:"
        echo "  bash install.sh --install    # full installation"
        echo "  bash install.sh --verify     # verify only"
        ;;
esac

exit $FAIL
