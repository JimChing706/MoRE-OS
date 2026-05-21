#!/usr/bin/env bash

export ANTHROPIC_API_KEY="sk-ant-api03-local-proxy-key"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$PROJECT_DIR/scripts"
ENV_FILE="$PROJECT_DIR/.env.local"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

source "$ENV_FILE" 2>/dev/null || true

start_local_llm_server() {
    local server_port=8080

    if curl -s --max-time 1 "http://localhost:$server_port/health" >/dev/null 2>&1; then
        return 0
    fi

    echo "启动本地 LLM API 服务器..."
    nohup python3 "$SCRIPT_DIR/local-llm-server.py" $server_port > /tmp/local-llm-server.log 2>&1 &
    sleep 3

    if curl -s --max-time 1 "http://localhost:$server_port/health" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ 本地 LLM 服务器已启动 (端口 $server_port)${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ 本地 LLM 服务器启动失败${NC}"
        return 1
    fi
}

start_local_proxy() {
    local proxy_port=8000

    if curl -s --max-time 1 "http://localhost:$proxy_port/v1/models" >/dev/null 2>&1; then
        return 0
    fi

    echo "启动本地 API 代理..."
    nohup python3 "$SCRIPT_DIR/local-proxy.py" $proxy_port > /tmp/local-proxy.log 2>&1 &
    sleep 2

    if curl -s --max-time 1 "http://localhost:$proxy_port/v1/models" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ 本地代理已启动 (端口 $proxy_port)${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ 本地代理启动失败，将尝试直接连接${NC}"
        return 1
    fi
}

start_local_proxy

LMSTUDIO_AVAILABLE=false
OLLAMA_AVAILABLE=false
LMSTUDIO_MODELS=()
OLLAMA_MODELS=()

check_services() {
    if curl -s --max-time 2 "http://localhost:1234/v1/models" >/dev/null 2>&1; then
        LMSTUDIO_AVAILABLE=true
        LMSTUDIO_MODELS=($(curl -s "http://localhost:1234/v1/models" | python3 -c "import sys,json; print(' '.join([m['id'] for m in json.load(sys.stdin).get('data',[])]))" 2>/dev/null))
    fi

    if curl -s --max-time 2 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
        OLLAMA_AVAILABLE=true
        OLLAMA_MODELS=($(curl -s "http://localhost:11434/api/tags" | python3 -c "import sys,json; print(' '.join([m['name'] for m in json.load(sys.stdin).get('models',[])]))" 2>/dev/null))
    fi
}

get_status() {
    local status_line=""

    if [ -n "$ANTHROPIC_API_KEY" ]; then
        status_line="${GREEN}●${NC} API Key: 已配置"
    else
        status_line="${YELLOW}○${NC} API Key: 未配置"
    fi

    if [ "$LMSTUDIO_AVAILABLE" = true ]; then
        status_line="$status_line  ${GREEN}●${NC} LM Studio: ${#LMSTUDIO_MODELS[@]} 个模型"
    else
        status_line="$status_line  ${YELLOW}○${NC} LM Studio: 不可用"
    fi

    if [ "$OLLAMA_AVAILABLE" = true ]; then
        status_line="$status_line  ${GREEN}●${NC} Ollama: ${#OLLAMA_MODELS[@]} 个模型"
    else
        status_line="$status_line  ${YELLOW}○${NC} Ollama: 不可用"
    fi

    echo -e "$status_line"
}

show_menu() {
    check_services

    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║     QNMing MoRE OS - Claude Code 一键启动           ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
    get_status
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${MAGENTA}🚀 快速启动${NC}"
    echo "    [1] 交互模式       - 启动 Claude Code 对话"
    echo "    [2] 快速任务       - 输入任务描述执行"
    echo ""
    echo -e "  ${MAGENTA}🔧 模型选择${NC}"
    echo "    [3] LM Studio     - 使用 LM Studio 本地模型"
    echo "    [4] Ollama        - 使用 Ollama 本地模型"
    echo "    [5] API Key       - 使用远程 Claude 模型"
    echo "    [6] 智能推荐      - 根据任务类型推荐模型"
    echo "    [7] 本地聊天      - 直接使用本地模型聊天 (无需网络)"
    echo ""
    echo -e "  ${MAGENTA}⚙️  管理功能${NC}"
    echo "    [8] 会话管理      - 查看/恢复/删除会话"
    echo "    [9] API Key 管理  - 设置/查看/验证 API Key"
    echo "   [10] 配置环境      - 首次配置本地模型"
    echo "   [11] 安装 MCP      - 安装 MCP 工具"
    echo "   [12] 代码检查      - 运行 pre-commit"
    echo ""
    echo -e "  ${MAGENTA}📊 工具${NC}"
    echo "   [13] 模型查看     - 列出所有可用模型"
    echo "   [14] 状态诊断     - 检查所有服务状态"
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${GREEN}快捷命令:${NC}"
    echo "    ./run-local-ai.sh i           # 交互模式"
    echo "    ./run-local-ai.sh t \"任务\"   # 快速任务"
    echo "    ./run-local-ai.sh lmstudio    # 使用 LM Studio"
    echo "    ./run-local-ai.sh ollama      # 使用 Ollama"
    echo "    ./run-local-ai.sh api         # 使用 API Key"
    echo ""
    echo -e "  ${GREEN}[q] 退出${NC}"
    echo ""
    read -p "请选择 [1-13/q]: " choice
}

run_interactive() {
    bash "$SCRIPT_DIR/claude-local-run.sh" --interactive
}

run_task() {
    echo ""
    read -p "请输入任务描述: " task
    if [ -n "$task" ]; then
        bash "$SCRIPT_DIR/claude-local-run.sh" --print "$task"
    fi
}

run_lmstudio() {
    local model="${LMSTUDIO_MODELS[0]:-qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled}"
    echo ""
    echo "可用模型:"
    for i in "${!LMSTUDIO_MODELS[@]}"; do
        echo "  [$i] ${LMSTUDIO_MODELS[$i]}"
    done
    echo ""
    read -p "选择模型 [0-${#LMSTUDIO_MODELS[@]}]: " idx
    if [ -n "$idx" ] && [ "$idx" -ge 0 ] && [ "$idx" -lt ${#LMSTUDIO_MODELS[@]} ]; then
        model="${LMSTUDIO_MODELS[$idx]}"
    fi
    echo -e "${GREEN}使用模型: $model${NC}"
    bash "$SCRIPT_DIR/claude-local-run.sh" --provider lmstudio --model "$model" --interactive
}

run_ollama() {
    local model="${OLLAMA_MODELS[0]:-qwen2.5:7b}"
    echo ""
    echo "可用模型:"
    for i in "${!OLLAMA_MODELS[@]}"; do
        echo "  [$i] ${OLLAMA_MODELS[$i]}"
    done
    echo ""
    read -p "选择模型 [0-${#OLLAMA_MODELS[@]}]: " idx
    if [ -n "$idx" ] && [ "$idx" -ge 0 ] && [ "$idx" -lt ${#OLLAMA_MODELS[@]} ]; then
        model="${OLLAMA_MODELS[$idx]}"
    fi
    echo -e "${GREEN}使用模型: $model${NC}"
    bash "$SCRIPT_DIR/claude-local-run.sh" --provider ollama --model "$model" --interactive
}

run_api_mode() {
    if [ -z "$ANTHROPIC_API_KEY" ]; then
        echo -e "${YELLOW}请先设置 API Key (选项 8)${NC}"
        return
    fi

    echo ""
    echo "可用模型:"
    echo "  [0] claude-sonnet-4-6 (默认)"
    echo "  [1] claude-opus-4-5"
    echo "  [2] claude-3-5-sonnet-20241022"
    echo ""
    read -p "选择模型 [0-2]: " idx

    case "$idx" in
        1) model="claude-opus-4-5" ;;
        2) model="claude-3-5-sonnet-20241022" ;;
        *) model="claude-sonnet-4-6" ;;
    esac

    echo -e "${GREEN}使用模型: $model${NC}"
    bash "$SCRIPT_DIR/claude-local-run.sh" --provider api --model "$model" --interactive
}

run_smart_select() {
    bash "$SCRIPT_DIR/model-selector.sh" --show
    echo ""
    read -p "请输入任务描述 (直接回车退出): " task
    if [ -n "$task" ]; then
        model=$(bash "$SCRIPT_DIR/model-selector.sh" -a "$task" 2>/dev/null | grep "推荐模型" | cut -d':' -f2 | tr -d ' ' || echo "lmstudio/${LMSTUDIO_MODELS[0]}")
        echo -e "${GREEN}推荐模型: $model${NC}"
        read -p "是否运行? (y/n): " confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            cd "$PROJECT_DIR" && claude -p "$task" --model "$model"
        fi
    fi
}

run_local_chat() {
    local model="${LMSTUDIO_MODELS[0]:-qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled}"
    echo ""
    echo "可用模型:"
    for i in "${!LMSTUDIO_MODELS[@]}"; do
        echo "  [$i] ${LMSTUDIO_MODELS[$i]}"
    done
    echo ""
    read -p "选择模型 [0-${#LMSTUDIO_MODELS[@]}]: " idx
    if [ -n "$idx" ] && [ "$idx" -ge 0 ] && [ "$idx" -lt ${#LMSTUDIO_MODELS[@]} ]; then
        model="${LMSTUDIO_MODELS[$idx]}"
    fi

    echo ""
    echo -e "${GREEN}使用模型: $model${NC}"
    echo -e "${GREEN}直接聊天模式 (无需网络连接)${NC}"
    echo -e "${YELLOW}输入 'quit' 或 'exit' 退出${NC}"
    echo ""

    bash "$SCRIPT_DIR/local-chat.sh" "$idx"
}

run_session_manager() {
    bash "$SCRIPT_DIR/session-manager.sh" list
    echo ""
    echo "操作:"
    echo "  [1] 恢复会话"
    echo "  [2] 删除会话"
    echo "  [3] 清理所有"
    echo "  [q] 返回"
    read -p "请选择 [1-3/q]: " sub_choice

    case "$sub_choice" in
        1)
            read -p "输入会话名称: " session_name
            bash "$SCRIPT_DIR/session-manager.sh" resume "$session_name"
            ;;
        2)
            read -p "输入会话名称: " session_name
            bash "$SCRIPT_DIR/session-manager.sh" delete "$session_name"
            ;;
        3)
            read -p "确认清理所有会话? (y/n): " confirm
            if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
                bash "$SCRIPT_DIR/session-manager.sh" clear
            fi
            ;;
    esac
}

run_api_key() {
    echo ""
    echo "API Key 管理:"
    echo "  [1] 设置 API Key"
    echo "  [2] 查看当前 Key"
    echo "  [3] 验证 Key 有效性"
    echo "  [4] 移除 API Key"
    echo "  [q] 返回"
    read -p "请选择 [1-4/q]: " sub_choice

    case "$sub_choice" in
        1)
            echo ""
            echo "获取 API Key: https://console.anthropic.com/settings/keys"
            read -p "输入 API Key (sk-ant-...): " api_key
            bash "$SCRIPT_DIR/set-api-key.sh" -s "$api_key"
source "$ENV_FILE" 2>/dev/null || true
set -e
            ;;
        2)
            bash "$SCRIPT_DIR/set-api-key.sh" -g
            ;;
        3)
            bash "$SCRIPT_DIR/set-api-key.sh" -c
            ;;
        4)
            read -p "确认移除 API Key? (y/n): " confirm
            if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
                bash "$SCRIPT_DIR/set-api-key.sh" -r
            fi
            ;;
    esac
}

run_setup() {
    bash "$SCRIPT_DIR/claude-local-setup.sh"
}

run_mcp() {
    bash "$SCRIPT_DIR/mcp-quickstart.sh"
}

run_workflow() {
    bash "$SCRIPT_DIR/dev-workflow.sh" pre-commit
}

show_models() {
    check_services
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║              可用模型列表                              ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""

    if [ "$LMSTUDIO_AVAILABLE" = true ]; then
        echo -e "${GREEN}LM Studio (端口 1234) - ${#LMSTUDIO_MODELS[@]} 个模型:${NC}"
        for m in "${LMSTUDIO_MODELS[@]}"; do
            echo "  • $m"
        done
        echo ""
    else
        echo -e "${YELLOW}LM Studio: 不可用 (未运行)${NC}"
        echo ""
    fi

    if [ "$OLLAMA_AVAILABLE" = true ]; then
        echo -e "${GREEN}Ollama (端口 11434) - ${#OLLAMA_MODELS[@]} 个模型:${NC}"
        for m in "${OLLAMA_MODELS[@]}"; do
            echo "  • $m"
        done
        echo ""
    else
        echo -e "${YELLOW}Ollama: 不可用 (未运行)${NC}"
        echo ""
    fi

    if [ -n "$ANTHROPIC_API_KEY" ]; then
        echo -e "${GREEN}API Key 模式 (远程模型):${NC}"
        echo "  • claude-sonnet-4-6 (默认)"
        echo "  • claude-opus-4-5"
        echo "  • claude-3-5-sonnet-20241022"
    else
        echo -e "${YELLOW}API Key 模式: 未配置${NC}"
    fi
}

show_diagnose() {
    check_services
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║              服务状态诊断                              ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""

    echo -e "API Key 状态:"
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        echo -e "  ${GREEN}✓${NC} 已配置"
    else
        echo -e "  ${YELLOW}✗${NC} 未配置"
    fi
    echo ""

    echo -e "LM Studio 状态:"
    if [ "$LMSTUDIO_AVAILABLE" = true ]; then
        echo -e "  ${GREEN}✓${NC} 运行中 (端口 1234)"
        echo -e "  ${GREEN}✓${NC} ${#LMSTUDIO_MODELS[@]} 个模型已加载"
    else
        echo -e "  ${YELLOW}✗${NC} 未运行"
        echo "    启动: 打开 LM Studio 应用并加载模型"
    fi
    echo ""

    echo -e "Ollama 状态:"
    if [ "$OLLAMA_AVAILABLE" = true ]; then
        echo -e "  ${GREEN}✓${NC} 运行中 (端口 11434)"
        echo -e "  ${GREEN}✓${NC} ${#OLLAMA_MODELS[@]} 个模型已加载"
    else
        echo -e "  ${YELLOW}✗${NC} 未运行"
        echo "    启动: ollama serve"
    fi
    echo ""

    echo -e "Claude Code 状态:"
    if claude auth status --text 2>/dev/null | grep -q "Logged in"; then
        echo -e "  ${GREEN}✓${NC} 已登录"
    elif [ -n "$ANTHROPIC_API_KEY" ]; then
        echo -e "  ${GREEN}✓${NC} API Key 模式可用"
    else
        echo -e "  ${YELLOW}✗${NC} 未登录"
    fi

    echo ""
    echo -e "${GREEN}诊断完成${NC}"
}

quick_start() {
    local cmd="$1"
    shift

    case "$cmd" in
        i|interactive)
            run_interactive
            ;;
        t|task)
            local task="$*"
            if [ -n "$task" ]; then
                bash "$SCRIPT_DIR/claude-local-run.sh" --print "$task"
            else
                read -p "请输入任务描述: " task
                [ -n "$task" ] && bash "$SCRIPT_DIR/claude-local-run.sh" --print "$task"
            fi
            ;;
        lmstudio)
            run_lmstudio
            ;;
        ollama)
            run_ollama
            ;;
        api)
            run_api_mode
            ;;
        chat|local)
            run_local_chat
            ;;
        models)
            show_models
            ;;
        status|diag)
            show_diagnose
            ;;
        help|-h|--help)
            echo "用法: $0 [命令]"
            echo ""
            echo "命令:"
            echo "  i, interactive    交互模式"
            echo "  t, task           快速任务"
            echo "  lmstudio          使用 LM Studio"
            echo "  ollama            使用 Ollama"
            echo "  api               使用 API Key"
            echo "  chat, local       本地聊天 (无需网络)"
            echo "  models            列出所有模型"
            echo "  status, diag      诊断状态"
            echo "  help              显示帮助"
            ;;
        *)
            show_menu
            ;;
    esac
}

if [ $# -gt 0 ]; then
    quick_start "$@"
else
    while true; do
        show_menu
        case "$choice" in
            1) run_interactive ;;
            2) run_task ;;
            3) run_lmstudio ;;
            4) run_ollama ;;
            5) run_api_mode ;;
            6) run_smart_select ;;
            7) run_local_chat ;;
            8) run_session_manager ;;
            9) run_api_key ;;
           10) run_setup ;;
           11) run_mcp ;;
           12) run_workflow ;;
           13) show_models ;;
           14) show_diagnose ;;
            q|Q) exit 0 ;;
            *) echo "无效选择，请重试" ;;
        esac
    done
fi