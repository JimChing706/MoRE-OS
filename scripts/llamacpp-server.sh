#!/usr/bin/env bash
# ============================================================
# llama.cpp Server Launcher — Qwen3.8-Flash-Next (Mac 48GB)
# ============================================================
# Usage:
#   ./scripts/llamacpp-server.sh start    # start server
#   ./scripts/llamacpp-server.sh stop     # stop server
#   ./scripts/llamacpp-server.sh restart  # stop + start
#   ./scripts/llamacpp-server.sh status   # check status
#   ./scripts/llamacpp-server.sh download # download GGUF model
#   ./scripts/llamacpp-server.sh logs     # tail server logs
# ============================================================
set -euo pipefail

PORT="${LLAMACPP_PORT:-8090}"
HOST="${LLAMACPP_HOST:-127.0.0.1}"
MODEL_DIR="${LLAMACPP_MODEL_DIR:-$HOME/models}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${LLAMACPP_VENV:-$SCRIPTS_DIR/../.venv}"
# Model: Qwen3.8-27B (qwen3_5 arch) — fits comfortably in 48GB unified memory.
# UD-Q6_K = 21.98GB single-file GGUF. ~20-30 tok/s on M5 Pro.
MODEL_REPO="${LLAMACPP_REPO:-unsloth/Qwen3.8-27B-GGUF}"
MODEL_QUANT="${LLAMACPP_QUANT:-UD-Q6_K}"
CONTEXT_LEN="${LLAMACPP_CTX:-8192}"
N_GPU_LAYERS="${LLAMACPP_NGL:-99}"
LOG_FILE="/tmp/llamacpp-qwen38.log"
PID_FILE="/tmp/llamacpp-qwen38.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

find_model() {
    find "$MODEL_DIR" -name "*.gguf" -path "*${MODEL_QUANT}.gguf" -print -quit 2>/dev/null
}

    do_download() {
    INCLUDE_PATTERN="*${MODEL_QUANT}.gguf"
    echo -e "${CYAN}Downloading ${MODEL_REPO} (${MODEL_QUANT}, ~22GB)...${NC}"
    mkdir -p "$MODEL_DIR"
    local hf_cmd=""
    # Prefer a huggingface_hub CLI. Use the project venv if it has one, else system pip.
    for c in "$VENV/bin/hf" "$VENV/bin/huggingface-cli" "$(command -v hf || true)" "$(command -v huggingface-cli || true)"; do
        if [ -n "$c" ] && [ -x "$c" ]; then hf_cmd="$c"; break; fi
    done
    if [ -z "$hf_cmd" ]; then
        echo -e "${CYAN}Installing huggingface_hub CLI...${NC}"
        if [ -n "$VENV" ] && [ -x "$VENV/bin/pip" ]; then
            "$VENV/bin/pip" install -U "huggingface_hub[cli]"
            hf_cmd="$VENV/bin/hf"
        else
            pip install -U "huggingface_hub[cli]"
            hf_cmd="$(command -v hf || true)"
        fi
    fi
    "$hf_cmd" download "$MODEL_REPO" --local-dir "$MODEL_DIR" --include "$INCLUDE_PATTERN"
    echo -e "${GREEN}Download complete.${NC}"
    echo "Model dir: $MODEL_DIR"
    find "$MODEL_DIR" -name "*.gguf" -path "*${MODEL_QUANT}.gguf" -exec ls -lh {} \;
}

do_start() {
    local model_path
    model_path=$(find_model)
    if [ -z "$model_path" ]; then
        echo -e "${YELLOW}Model not found (quant: ${MODEL_QUANT}). Run: $0 download${NC}"
        exit 1
    fi

    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo -e "${GREEN}llama.cpp already running (PID $(cat "$PID_FILE"))${NC}"
        return
    fi

    # Prefer the source-built binary (has qwen4exp support) over the Homebrew one.
    SERVER_BIN="${LLAMACPP_SERVER_BIN:-}"
    if [ -z "$SERVER_BIN" ]; then
        for cand in "$HOME/.local/bin/llama-server" "$HOME/src/llama.cpp/build/bin/llama-server"; do
            if [ -x "$cand" ]; then SERVER_BIN="$cand"; break; fi
        done
    fi
    if [ -z "$SERVER_BIN" ] || ! command -v "${SERVER_BIN##*/}" &>/dev/null; then
        if [ -z "$SERVER_BIN" ]; then
            echo -e "${YELLOW}llama-server not found.${NC}"
            echo "Install options:"
            echo "  1. bash scripts/install-llamacpp.sh  (build from source with qwen3_5/qwen4exp support)"
            echo "  2. brew install llama.cpp  (NOTE: Homebrew releases may lack qwen4exp support)"
            exit 1
        fi
    fi
    SERVER_BIN="$(command -v "$SERVER_BIN" 2>/dev/null || echo "$SERVER_BIN")"

    echo -e "${CYAN}Starting llama.cpp server...${NC}"
    echo "  Model: $(basename "$model_path")"
    echo "  Port:  $PORT"
    echo "  CTX:   $CONTEXT_LEN"
    echo "  NGL:   $N_GPU_LAYERS"
    echo "  Key flags: --jinja -fa on (Qwen3.8-27B)"

    nohup "$SERVER_BIN" \
        -m "$model_path" \
        --host "$HOST" \
        --port "$PORT" \
        -c "$CONTEXT_LEN" \
        -ngl "$N_GPU_LAYERS" \
        --jinja \
        -fa on \
        --metrics \
        > "$LOG_FILE" 2>&1 &

    echo $! > "$PID_FILE"
    sleep 3

    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo -e "${GREEN}llama.cpp server started (PID $(cat "$PID_FILE"))${NC}"
        echo "  API: http://${HOST}:${PORT}/v1"
        echo "  Log: $LOG_FILE"
        echo "  Health: curl -s http://${HOST}:${PORT}/health"
    else
        echo -e "${RED}Failed to start. Check: $LOG_FILE${NC}"
        tail -20 "$LOG_FILE" 2>/dev/null
        exit 1
    fi
}

do_stop() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo -n "Stopping llama.cpp (PID $pid)..."
            kill "$pid"
            sleep 2
            if kill -0 "$pid" 2>/dev/null; then
                echo -n " force killing..."
                kill -9 "$pid"
            fi
            echo -e " ${GREEN}done${NC}"
        else
            echo "llama.cpp process (PID $pid) already exited."
        fi
        rm -f "$PID_FILE"
    else
        echo "No llama.cpp process found."
    fi
}

do_status() {
    echo -e "${CYAN}── llama.cpp Server${NC}"
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo -e "  ${GREEN}●${NC} Running (PID $(cat "$PID_FILE"))"
        curl -s --max-time 3 "http://${HOST}:${PORT}/health" 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    status = d.get('status','unknown')
    print(f'  Health: {status}')
except: print('  Health: cannot reach server')
" 2>/dev/null || echo "  Health: cannot reach server"
        curl -s --max-time 3 "http://${HOST}:${PORT}/v1/models" 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for m in d.get('data',[]):
        print(f'  Model: {m[\"id\"]}')
except: pass
" 2>/dev/null
    else
        echo -e "  ${YELLOW}○${NC} Not running"
    fi
    echo ""
    echo -e "${CYAN}── Model Files${NC}"
    local model_path
    model_path=$(find_model)
    if [ -n "$model_path" ]; then
        ls -lh "$model_path" 2>/dev/null
    else
        echo "  No GGUF model found (quant: ${MODEL_QUANT})"
        echo "  Run: $0 download"
    fi
}

do_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "No log file at $LOG_FILE"
    fi
}

case "${1:-}" in
    start)    do_start ;;
    stop)     do_stop ;;
    restart)  do_stop; sleep 1; do_start ;;
    status)   do_status ;;
    download) do_download ;;
    logs)     do_logs ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|download|logs}"
        echo ""
        echo "Environment variables:"
        echo "  LLAMACPP_REPO       Model repo (default: unsloth/Qwen3.8-27B-GGUF)"
        echo "  LLAMACPP_QUANT      Quantization (default: UD-Q6_K)"
        echo "  LLAMACPP_PORT       Server port (default: 8090)"
        echo "  LLAMACPP_HOST       Bind host (default: 127.0.0.1)"
        echo "  LLAMACPP_MODEL_DIR  Model directory (default: ~/models)"
        echo "  LLAMACPP_CTX        Context length (default: 8192)"
        echo "  LLAMACPP_NGL        GPU layers (default: 99)"
        echo "  LLAMACPP_SERVER_BIN Path to llama-server binary (default: auto-detect)"
        ;;
esac
