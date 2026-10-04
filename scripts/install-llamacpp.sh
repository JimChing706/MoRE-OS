#!/usr/bin/env bash
# ============================================================
# Build llama.cpp with Qwen3.8-Flash-Next support (qwen4exp)
# ============================================================
# Usage:
#   bash scripts/install-llamacpp.sh            # build from source
#   bash scripts/install-llamacpp.sh brew       # install via Homebrew
# ============================================================
set -euo pipefail

BUILD_DIR="${HOME}/src/llama.cpp"
PREFIX="${HOME}/.local"
NPROC=$(sysctl -n hw.ncpu)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

do_brew() {
    echo -e "${CYAN}Installing llama.cpp via Homebrew...${NC}"
    brew install llama.cpp
    echo -e "${GREEN}Done. Verify: llama-server --version${NC}"
}

do_build() {
    echo -e "${CYAN}Building llama.cpp with qwen4exp support...${NC}"

    if [ -d "$BUILD_DIR" ]; then
        cd "$BUILD_DIR"
        git fetch origin
    else
        git clone https://github.com/ggml-org/llama.cpp "$BUILD_DIR"
        cd "$BUILD_DIR"
    fi

    # qwen4exp (Qwen3.8-Flash-Next) support merged into master via PR #27742 (2026-08-27).
    # Build latest master to get it, plus follow-up fixes (PR #27941, MTP draft head #27836).
    echo -e "${CYAN}Building latest master (includes qwen4exp support)...${NC}"
    git checkout master || git checkout main
    git pull --ff-only origin master 2>/dev/null || git pull --ff-only origin main 2>/dev/null || true

    echo -e "${CYAN}Building with Metal support (${NPROC} cores)...${NC}"
    cmake -B build -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=OFF
    cmake --build build --config Release -j "$NPROC" \
        --target llama-cli llama-server llama-mtmd-cli

    echo -e "${CYAN}Installing to ${PREFIX}/bin/...${NC}"
    mkdir -p "$PREFIX/bin"
    cp build/bin/llama-* "$PREFIX/bin/"

    echo ""
    echo -e "${GREEN}Installed to ${PREFIX}/bin/${NC}"
    echo "  llama-server   — HTTP API (OpenAI-compat)"
    echo "  llama-cli      — CLI chat"
    echo "  llama-mtmd-cli — multimodal CLI"
    echo ""
    echo "Add to PATH:"
    echo "  export PATH=\"\${HOME}/.local/bin:\$PATH\""
    echo ""
    echo -e "${YELLOW}Verify: ${HOME}/.local/bin/llama-server --version${NC}"
}

case "${1:-}" in
    brew)    do_brew ;;
    build|*) do_build ;;
esac
