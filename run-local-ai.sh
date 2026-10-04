#!/usr/bin/env bash
# ============================================================
# QNMing MoRE OS — Service Launcher & Status Dashboard
# ============================================================
# Usage:
#   ./run-local-ai.sh              # interactive menu
#   ./run-local-ai.sh start        # start all services
#   ./run-local-ai.sh stop         # stop all services
#   ./run-local-ai.sh status       # service status
#   ./run-local-ai.sh health       # health check
#   ./run-local-ai.sh chat         # local LLM chat
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$ROOT_DIR/scripts"
API_PORT="${MORE_PORT:-8011}"

# ============================================================
show_banner() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║        QNMing MoRE OS — v0.8.0                       ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${NC}"
}

# ============================================================
check_service() {
    local port="$1" label="$2"
    if lsof -i :$port -s TCP:LISTEN >/dev/null 2>&1; then
        echo -e "  ${GREEN}●${NC} $label (port $port)"
        return 0
    else
        echo -e "  ${YELLOW}○${NC} $label (port $port)"
        return 1
    fi
}

show_status() {
    show_banner
    echo ""
    echo -e "${CYAN}── Services${NC}"
    check_service "$API_PORT" "MoRE OS API"
    check_service 3003 "Dashboard"
    echo ""
    echo -e "${CYAN}── LLM Providers${NC}"
    if curl -s --max-time 2 http://localhost:1234/v1/models >/dev/null 2>&1; then
        N=$(curl -s http://localhost:1234/v1/models | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo "?")
        echo -e "  ${GREEN}●${NC} LM Studio ($N models)"
    else
        echo -e "  ${YELLOW}○${NC} LM Studio (offline)"
    fi
    if curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
        N=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
        echo -e "  ${GREEN}●${NC} Ollama ($N models)"
    else
        echo -e "  ${YELLOW}○${NC} Ollama (offline)"
    fi
    if curl -s --max-time 2 http://localhost:8090/v1/models >/dev/null 2>&1; then
        N=$(curl -s http://localhost:8090/v1/models | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo "?")
        echo -e "  ${GREEN}●${NC} llama.cpp Qwen3.8 ($N models)"
    else
        echo -e "  ${YELLOW}○${NC} llama.cpp (offline)"
    fi
    echo ""
}

# ============================================================
do_start() {
    show_banner
    echo ""

    # Start API
    if lsof -i :$API_PORT -s TCP:LISTEN >/dev/null 2>&1; then
        echo -e "${GREEN}API already running on port $API_PORT${NC}"
    else
        echo -n "Starting MoRE OS API on port $API_PORT..."
        nohup "$ROOT_DIR/.venv/bin/python" -m more_core.cli serve \
            --host 0.0.0.0 --port $API_PORT \
            > /tmp/more-os-api.log 2>&1 &
        sleep 2
        if lsof -i :$API_PORT -s TCP:LISTEN >/dev/null 2>&1; then
            echo -e " ${GREEN}OK${NC}"
        else
            echo -e " ${RED}FAILED${NC} — check /tmp/more-os-api.log"
        fi
    fi

    # R-19: llama.cpp 默认不再自动拉起 —— 27B 模型会耗尽内存并把 API 一起 OOM 杀掉。
    # 需要时显式设置 MORE_START_LLAMACPP=1。
    if [ "${MORE_START_LLAMACPP:-0}" = "1" ] && [ -x "$ROOT_DIR/scripts/llamacpp-server.sh" ]; then
        LLAMACPP_MODEL_DIR="${LLAMACPP_MODEL_DIR:-$HOME/models}"
        MODEL_PATH=$(find "$LLAMACPP_MODEL_DIR" -name "*.gguf" -path "*UD-Q6_K*" -print -quit 2>/dev/null)
        if [ -n "$MODEL_PATH" ]; then
            bash "$ROOT_DIR/scripts/llamacpp-server.sh" start
        else
            echo -e "${YELLOW}  llama.cpp: model not found (run: scripts/llamacpp-server.sh download)${NC}"
        fi
    fi
    echo ""
    echo "Services started. Dashboard:"
    echo "  cd app && npm run dev          # frontend (separate terminal)"
    echo "  http://localhost:$API_PORT/api/v1/health   # API health"
    echo "  http://localhost:$API_PORT/docs            # API docs"
}

do_stop() {
    echo -n "Stopping MoRE OS API..."
    pkill -f "more_core.cli serve" 2>/dev/null || true
    echo " done."
    if [ -x "$ROOT_DIR/scripts/llamacpp-server.sh" ]; then
        bash "$ROOT_DIR/scripts/llamacpp-server.sh" stop
    fi
}

# ============================================================
do_chat() {
    echo ""
    echo -e "${CYAN}Local LLM Chat${NC}"
    echo ""

    # Check available providers
    USE_LMSTUDIO=false; USE_OLLAMA=false; USE_LLAMACPP=false
    curl -s --max-time 2 http://localhost:1234/v1/models >/dev/null 2>&1 && USE_LMSTUDIO=true
    curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 && USE_OLLAMA=true
    curl -s --max-time 2 http://localhost:8090/v1/models >/dev/null 2>&1 && USE_LLAMACPP=true

    if ! $USE_LMSTUDIO && ! $USE_OLLAMA && ! $USE_LLAMACPP; then
        echo -e "${RED}No LLM provider available. Start LM Studio, Ollama, or llama.cpp first.${NC}"
        return
    fi

    # Select provider
    if $USE_LMSTUDIO && $USE_OLLAMA && $USE_LLAMACPP; then
        echo "Providers: [1] LM Studio  [2] Ollama  [3] llama.cpp Qwen3.8"
        read -p "Select [1/2/3]: " choice
        if [ "$choice" = "2" ]; then USE_LMSTUDIO=false; USE_LLAMACPP=false
        elif [ "$choice" = "3" ]; then USE_LMSTUDIO=false; USE_OLLAMA=false
        fi
    elif $USE_LMSTUDIO && $USE_LLAMACPP; then
        echo "Providers: [1] LM Studio  [2] llama.cpp Qwen3.8"
        read -p "Select [1/2]: " choice
        if [ "$choice" = "2" ]; then USE_LMSTUDIO=false; USE_OLLAMA=false; fi
    elif $USE_OLLAMA && $USE_LLAMACPP; then
        echo "Providers: [1] Ollama  [2] llama.cpp Qwen3.8"
        read -p "Select [1/2]: " choice
        if [ "$choice" = "2" ]; then USE_LMSTUDIO=false; USE_OLLAMA=false; fi
    elif $USE_LMSTUDIO && $USE_OLLAMA; then
        echo "Providers: [1] LM Studio  [2] Ollama"
        read -p "Select [1/2]: " choice
        if [ "$choice" = "2" ]; then USE_LMSTUDIO=false; fi
    elif $USE_LMSTUDIO; then
        echo "Using LM Studio"
    elif $USE_LLAMACPP; then
        echo "Using llama.cpp Qwen3.8"
        USE_LMSTUDIO=false; USE_OLLAMA=false
    else
        echo "Using Ollama"
    fi

    # Run chat
    if [ -f "$SCRIPT_DIR/lmstudio-chat.py" ] && $USE_LMSTUDIO; then
        python3 "$SCRIPT_DIR/lmstudio-chat.py" --interactive
    elif [ -f "$SCRIPT_DIR/lmstudio-chat.py" ] && $USE_LLAMACPP; then
        python3 "$SCRIPT_DIR/lmstudio-chat.py" --provider llamacpp --interactive
    elif [ -f "$SCRIPT_DIR/lmstudio-chat.py" ]; then
        python3 "$SCRIPT_DIR/lmstudio-chat.py" --provider ollama --interactive
    else
        echo -e "${RED}lmstudio-chat.py not found${NC}"
    fi
}

# ============================================================
show_menu() {
    show_status
    echo -e "${MAGENTA}── Commands${NC}"
    echo "  [1] start      — start all services"
    echo "  [2] stop       — stop all services"
    echo "  [3] restart    — stop + start"
    echo "  [4] health     — full health check"
    echo "  [5] chat       — local LLM chat"
    echo "  [6] models     — list available models"
    echo "  [7] logs       — tail API logs"
    echo "  [q] quit"
    echo ""
    read -p "Select [1-7/q]: " choice

    case "$choice" in
        1|start)   do_start ;;
        2|stop)    do_stop ;;
        3|restart) do_stop; sleep 1; do_start ;;
        4|health)  bash "$SCRIPT_DIR/health_check.sh" ;;
        5|chat)    do_chat ;;
        6|models)
            echo ""
            if curl -s --max-time 2 http://localhost:1234/v1/models >/dev/null 2>&1; then
                echo -e "${GREEN}LM Studio:${NC}"
                curl -s http://localhost:1234/v1/models | python3 -c "
import sys,json
for m in json.load(sys.stdin).get('data',[]):
    print(f'  • {m[\"id\"]}')
" 2>/dev/null
            fi
            if curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
                echo -e "${GREEN}Ollama:${NC}"
                curl -s http://localhost:11434/api/tags | python3 -c "
import sys,json
for m in json.load(sys.stdin).get('models',[]):
    print(f'  • {m[\"name\"]}')
" 2>/dev/null
            fi
            if curl -s --max-time 2 http://localhost:8090/v1/models >/dev/null 2>&1; then
                echo -e "${GREEN}llama.cpp:${NC}"
                curl -s http://localhost:8090/v1/models | python3 -c "
import sys,json
for m in json.load(sys.stdin).get('data',[]):
    print(f'  • {m[\"id\"]}')
" 2>/dev/null
            fi
            ;;
        7|logs)
            if [ -f /tmp/more-os-api.log ]; then
                tail -f /tmp/more-os-api.log
            else
                echo "No log file at /tmp/more-os-api.log"
            fi
            ;;
        q|Q) exit 0 ;;
        *) echo "Invalid choice" ;;
    esac
}

# ============================================================
case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; sleep 1; do_start ;;
    status)  show_status ;;
    health)  bash "$SCRIPT_DIR/health_check.sh" ;;
    chat)    do_chat ;;
    models)
        shift
        show_banner
        echo -e "\n${GREEN}LM Studio:${NC}"
        curl -s --max-time 2 http://localhost:1234/v1/models | python3 -c "import sys,json; [print(f'  • {m[\"id\"]}') for m in json.load(sys.stdin).get('data',[])]" 2>/dev/null || echo "  offline"
        echo -e "\n${GREEN}Ollama:${NC}"
        curl -s --max-time 2 http://localhost:11434/api/tags | python3 -c "import sys,json; [print(f'  • {m[\"name\"]}') for m in json.load(sys.stdin).get('models',[])]" 2>/dev/null || echo "  offline"
        echo -e "\n${GREEN}llama.cpp:${NC}"
        curl -s --max-time 2 http://localhost:8090/v1/models | python3 -c "import sys,json; [print(f'  • {m[\"id\"]}') for m in json.load(sys.stdin).get('data',[])]" 2>/dev/null || echo "  offline"
        ;;
    help|-h|--help)
        echo "Usage: ./run-local-ai.sh [command]"
        echo ""
        echo "Commands:"
        echo "  start     Start MoRE OS API"
        echo "  stop      Stop MoRE OS API"
        echo "  restart   Restart MoRE OS API"
        echo "  status    Show service status"
        echo "  health    Full health check"
        echo "  chat      Local LLM chat"
        echo "  models    List available LLM models"
        echo "  (none)    Interactive menu"
        ;;
    *)
        while true; do
            show_menu
            echo ""
        done
        ;;
esac
