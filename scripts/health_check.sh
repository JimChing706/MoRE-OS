#!/usr/bin/env bash
# ============================================================
# QNMing MoRE OS — Full Stack Health Check
# ============================================================
# Usage: bash scripts/health_check.sh
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

PASS=0; FAIL=0; WARN=0
API_PORT="${MORE_PORT:-8011}"

# ---- API key support (MORE_API_KEY or more_core/.env) -----------------------
if [ -z "${MORE_API_KEY:-}" ]; then
    for _env in "$(dirname "${BASH_SOURCE[0]}")/../more_core/.env" "$(dirname "${BASH_SOURCE[0]}")/../.env"; do
        if [ -f "$_env" ]; then
            _k=$(grep -E '^MORE_API_KEY=' "$_env" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
            if [ -n "$_k" ]; then MORE_API_KEY="$_k"; break; fi
        fi
    done
fi
AUTH=()
if [ -n "${MORE_API_KEY:-}" ]; then AUTH=(-H "Authorization: Bearer ${MORE_API_KEY}"); fi
apicurl() { curl -s --max-time 5 "${AUTH[@]}" "$@"; }

ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; WARN=$((WARN + 1)); }
h2()   { echo -e "\n${CYAN}── $1${NC}"; }

# ============================================================
h2 "MoRE OS API (port $API_PORT)"

if lsof -i :$API_PORT -s TCP:LISTEN >/dev/null 2>&1; then
    RESP=$(apicurl "http://localhost:$API_PORT/api/v1/health")
    if echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('status')=='healthy' else 1)" 2>/dev/null; then
        VER=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))")
        ok "healthy — version $VER"
    else
        fail "unhealthy response"
    fi

    # LLM providers
    PROV=$(apicurl "http://localhost:$API_PORT/api/v1/health" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('llm_providers',[])))" 2>/dev/null)
    ok "LLM providers: $PROV"

    # Feature gates
    GATES=$(apicurl "http://localhost:$API_PORT/api/v1/health" | python3 -c "
import sys,json
g=json.load(sys.stdin).get('gates',{})
print(f\"symbolic={g.get('symbolic')}, evolution={g.get('evolution')}, metacognition={g.get('metacognition')}\")
" 2>/dev/null)
    ok "Gates: $GATES"
else
    fail "API not listening on port $API_PORT"
fi

# ============================================================
h2 "LLM Providers"

# LM Studio
if curl -s --max-time 3 http://localhost:1234/v1/models >/dev/null 2>&1; then
    COUNT=$(curl -s http://localhost:1234/v1/models | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo "?")
    ok "LM Studio running — $COUNT model(s)"
else
    warn "LM Studio offline (port 1234)"
fi

# Ollama
if curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    COUNT=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
    ok "Ollama running — $COUNT model(s)"
else
    warn "Ollama offline (port 11434)"
fi

# ============================================================
h2 "Frontend Dashboard"

for PORT in 3003 3002; do
    if lsof -i :$PORT -s TCP:LISTEN >/dev/null 2>&1; then
        HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:$PORT" 2>/dev/null)
        ok "Frontend serving on port $PORT (HTTP $HTTP)"
        break
    fi
done
if [ $PASS -eq 0 ] || ! lsof -i :3003 -s TCP:LISTEN >/dev/null 2>&1 && ! lsof -i :3002 -s TCP:LISTEN >/dev/null 2>&1; then
    warn "Frontend not running (start: cd app && npm run dev)"
fi

# ============================================================
h2 "Database Files"

for DB in data/outputs.db data/memory.db data/evolution.db; do
    if [ -f "$DB" ]; then
        SIZE=$(ls -lh "$DB" | awk '{print $5}')
        ok "$DB ($SIZE)"
    else
        warn "$DB missing — will be created on first write"
    fi
done

# ============================================================
h2 "Plugin Directories"

if [ -d plugins ]; then
    PLUGINS=$(ls -d plugins/*/ 2>/dev/null | wc -l | tr -d ' ')
    ok "$PLUGINS plugin(s) found"
else
    warn "plugins/ directory missing"
fi

# ============================================================
# Summary
# ============================================================

echo ""
echo -e "╔══════════════════════════════════════════════╗"
echo -e "║  Health Check Summary                         ║"
echo -e "╠══════════════════════════════════════════════╣"
printf "║  ${GREEN}%-8s %2d${NC}                              ║\n" "Passed:" $PASS
printf "║  ${YELLOW}%-8s %2d${NC}                              ║\n" "Warnings:" $WARN
printf "║  ${RED}%-8s %2d${NC}                              ║\n" "Failed:" $FAIL
echo -e "╚══════════════════════════════════════════════╝"

if [ $FAIL -gt 0 ]; then
    echo -e "\n${RED}Some checks failed. Run 'make start' to launch services.${NC}"
    exit 1
elif [ $WARN -gt 0 ]; then
    echo -e "\n${YELLOW}All critical services OK — some optional services offline.${NC}"
    exit 0
else
    echo -e "\n${GREEN}All systems nominal.${NC}"
    exit 0
fi
