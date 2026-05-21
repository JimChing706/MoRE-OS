#!/usr/bin/env bash
set -e

export ANTHROPIC_API_KEY="sk-ant-api03-local-proxy-key"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LMSTUDIO_AVAILABLE=false
OLLAMA_AVAILABLE=false

LMSTUDIO_MODELS=()
OLLAMA_MODELS=()

check_lmstudio() {
    if curl -s --max-time 3 "http://localhost:1234/v1/models" >/dev/null 2>&1; then
        LMSTUDIO_AVAILABLE=true
        local response=$(curl -s "http://localhost:1234/v1/models")
        LMSTUDIO_MODELS=($(echo "$response" | python3 -c "import sys,json; print(' '.join([m['id'] for m in json.load(sys.stdin).get('data',[])]))" 2>/dev/null))
    fi
}

check_ollama() {
    if curl -s --max-time 3 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
        OLLAMA_AVAILABLE=true
        local response=$(curl -s "http://localhost:11434/api/tags")
        OLLAMA_MODELS=($(echo "$response" | python3 -c "import sys,json; print(' '.join([m['name'] for m in json.load(sys.stdin).get('models',[])]))" 2>/dev/null))
    fi
}

check_claude_auth() {
    if claude auth status --text 2>/dev/null | grep -q "Logged in"; then
        return 0
    fi
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        return 0
    fi
    return 1
}

check_api_key() {
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        return 0
    fi
    return 1
}

show_help() {
    echo "用法: $0 [选项] [任务描述]"
    echo ""
    echo "选项:"
    echo "  -h, --help              显示帮助"
    echo "  -p, --provider PROVIDER 指定模型平台 (lmstudio|ollama|auto)"
    echo "  -m, --model MODEL      指定模型名称"
    echo "  -t, --turns N          最大交互轮数 (默认: 10)"
    echo "  -i, --interactive      交互模式"
    echo "  --login                登录 Claude Code"
    echo "  --resume SESSION       恢复会话"
    echo "  --continue             继续最近会话"
    echo ""
    echo "  --mcp                  启用 MCP 工具"
    echo "  --workflow CMD         运行工作流 (lint|format|typecheck|test|pre-commit)"
    echo "  --template TEMPLATE    使用提示词模板 (review|bug|feature|refactor|test|docs)"
    echo ""
    echo "快捷命令:"
    echo "  $0 setup               配置本地模型环境"
    echo "  $0 mcp                 安装 MCP 工具"
    echo "  $0 workflow pre-commit 运行完整检查"
    echo ""
    echo "示例:"
    echo "  $0 --login                      # 登录 Claude Code"
    echo "  $0 setup                       # 首次配置"
    echo "  $0 --print '修复 auth.py 中的 bug'"
    echo "  $0 --provider lmstudio --print '使用LM Studio'"
    echo "  $0 --interactive"
    echo "  $0 --mcp --print '使用MCP工具'"
    echo "  $0 workflow pre-commit"
}

detect_best_provider() {
    if [ "$LMSTUDIO_AVAILABLE" = true ]; then
        echo "lmstudio"
    elif [ "$OLLAMA_AVAILABLE" = true ]; then
        echo "ollama"
    else
        echo "none"
    fi
}

PROVIDER="auto"
MODEL=""
MAX_TURNS=10
MODE="print"
RESUME=""
CONTINUE=""
TASK=""
DO_LOGIN=false
ENABLE_MCP=false
WORKFLOW_CMD=""
TEMPLATE=""
DO_SETUP=false
DO_MCP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -p|--provider)
            PROVIDER="$2"
            shift 2
            ;;
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        -t|--turns)
            MAX_TURNS="$2"
            shift 2
            ;;
        -i|--interactive)
            MODE="interactive"
            shift
            ;;
        --login)
            DO_LOGIN=true
            shift
            ;;
        --resume)
            RESUME="--resume $2"
            shift 2
            ;;
        --continue)
            CONTINUE="--continue"
            shift
            ;;
        --mcp)
            ENABLE_MCP=true
            shift
            ;;
        --workflow)
            WORKFLOW_CMD="$2"
            shift 2
            ;;
        --template)
            TEMPLATE="$2"
            shift 2
            ;;
        setup)
            DO_SETUP=true
            shift
            ;;
        mcp)
            DO_MCP=true
            shift
            ;;
        workflow)
            WORKFLOW_CMD="$2"
            shift 2
            ;;
        *)
            TASK="$1"
            shift
            ;;
    esac
done

if [ "$DO_LOGIN" = true ]; then
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  Claude Code 登录${NC}"
    echo -e "${BLUE}==============================================${NC}"
    echo ""
    echo "请选择登录方式:"
    echo ""
    echo "  1. OAuth 登录 (浏览器) - 需要 Claude Pro/Max 订阅"
    echo "     命令: claude auth login"
    echo ""
    echo "  2. API Key 登录 (控制台) - 按量计费"
    echo "     命令: claude auth login --console"
    echo ""
    echo "  3. 设置 API Key 环境变量 (推荐本地模型)"
    echo "     命令: export ANTHROPIC_API_KEY=你的API密钥"
    echo ""
    echo "详细说明请访问: https://docs.claude.com/claude-code/auth"
    echo ""
    exit 0
fi

if [ "$DO_SETUP" = true ]; then
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  运行本地模型配置${NC}"
    echo -e "${BLUE}==============================================${NC}"
    bash "$PROJECT_DIR/scripts/claude-local-setup.sh"
    exit $?
fi

if [ "$DO_MCP" = true ]; then
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  安装 MCP 工具${NC}"
    echo -e "${BLUE}==============================================${NC}"
    bash "$PROJECT_DIR/scripts/mcp-quickstart.sh"
    exit $?
fi

if [ -n "$WORKFLOW_CMD" ]; then
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  运行工作流: $WORKFLOW_CMD${NC}"
    echo -e "${BLUE}==============================================${NC}"
    bash "$PROJECT_DIR/scripts/dev-workflow.sh" "$WORKFLOW_CMD"
    exit $?
fi

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}  Claude Code + 本地大模型 (双平台)${NC}"
echo -e "${BLUE}==============================================${NC}"
echo ""

echo -e "${YELLOW}[1/6] 检查 Claude Code 登录状态...${NC}"
if check_api_key; then
    echo -e "${GREEN}  ✓ ANTHROPIC_API_KEY 已配置 (API Key 模式)${NC}"
    USE_API_KEY=true
elif check_claude_auth; then
    echo -e "${GREEN}  ✓ 已登录 Claude Code${NC}"
    USE_API_KEY=false
else
    echo -e "${RED}  ✗ 未登录 Claude Code${NC}"
    echo ""
    echo -e "${YELLOW}  请选择登录方式:${NC}"
    echo "    方式1 (环境变量 - 推荐): export ANTHROPIC_API_KEY=你的密钥"
    echo "    方式2 (浏览器): claude auth login"
    echo "    方式3 (API Key): claude auth login --console"
    echo ""
    echo "  API Key 获取: https://console.anthropic.com/settings/keys"
    echo ""
    exit 1
fi

echo ""
echo -e "${YELLOW}[2/6] 检测本地模型平台...${NC}"
check_lmstudio
check_ollama

echo -e "  LM Studio: ${GREEN}可用${NC}" && echo -e "    模型: ${LMSTUDIO_MODELS[*]:-无}"
echo -e "  Ollama:   ${GREEN}可用${NC}" && echo -e "    模型: ${OLLAMA_MODELS[*]:-无}"

if [ "$PROVIDER" = "auto" ]; then
    if [ "$LMSTUDIO_AVAILABLE" = true ]; then
        PROVIDER="lmstudio"
    elif [ "$OLLAMA_AVAILABLE" = true ]; then
        PROVIDER="ollama"
    elif [ "$USE_API_KEY" = true ]; then
        PROVIDER="api"
    else
        PROVIDER="none"
    fi
fi

echo -e "\n  选择平台: ${CYAN}$PROVIDER${NC}"

echo ""
echo -e "${YELLOW}[3/6] 确定模型配置...${NC}"

case "$PROVIDER" in
    api)
        if [ -z "$MODEL" ]; then
            MODEL="claude-sonnet-4-6"
        fi
        MODEL_PREFIX=""
        echo -e "  模式: ${YELLOW}API Key (远程模型)${NC}"
        ;;
    lmstudio)
        if [ -z "$MODEL" ]; then
            MODEL="${LMSTUDIO_MODELS[0]:-qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled}"
        fi
        MODEL_PREFIX="lmstudio/"
        ;;
    ollama)
        if [ -z "$MODEL" ]; then
            MODEL="${OLLAMA_MODELS[0]:-qwen2.5:7b}"
        fi
        MODEL_PREFIX="ollama/"
        ;;
    none)
        echo -e "${RED}错误: 没有可用的本地模型平台${NC}"
        echo "  请设置 ANTHROPIC_API_KEY 环境变量使用远程模型"
        exit 1
        ;;
    *)
        echo -e "${RED}错误: 无效的模型平台: $PROVIDER${NC}"
        exit 1
        ;;
esac

echo -e "  使用模型: ${GREEN}$MODEL${NC}"

echo ""
echo -e "${YELLOW}[4/6] 验证模型服务...${NC}"

case "$PROVIDER" in
    api)
        if curl -s --max-time 10 -H "Authorization: Bearer $ANTHROPIC_API_KEY" \
            "https://api.anthropic.com/v1/models" 2>/dev/null | grep -q "$MODEL"; then
            echo -e "${GREEN}  ✓ API Key 有效，模型可用${NC}"
        else
            echo -e "${YELLOW}  警告: 尝试连接 Anthropic API...${NC}"
            if curl -s --max-time 5 "https://api.anthropic.com" >/dev/null 2>&1; then
                echo -e "${GREEN}  ✓ API 连接正常${NC}"
            else
                echo -e "${YELLOW}  警告: API 连接可能有问题${NC}"
            fi
        fi
        ;;
    lmstudio)
        if curl -s --max-time 5 "http://localhost:1234/v1/models" | grep -q "$MODEL"; then
            echo -e "${GREEN}  ✓ LM Studio 模型可用${NC}"
        else
            echo -e "${YELLOW}  警告: 模型可能未加载，请在 LM Studio 中加载${NC}"
        fi
        ;;
    ollama)
        if curl -s --max-time 5 "http://localhost:11434/api/tags" | grep -q "$MODEL"; then
            echo -e "${GREEN}  ✓ Ollama 模型可用${NC}"
        else
            echo -e "${YELLOW}  警告: 模型可能未加载${NC}"
        fi
        ;;
esac

echo ""
echo -e "${YELLOW}[5/6] 加载项目配置...${NC}"

CLAUDE_SETTINGS="$PROJECT_DIR/.claude/settings.json"
CLAUDE_MD="$PROJECT_DIR/.claude/CLAUDE.md"
CLAUDE_MCP="$PROJECT_DIR/.claude/mcp/servers.json"
CLAUDE_SHORTCUTS="$PROJECT_DIR/.claude/shortcuts.json"

[ -f "$CLAUDE_SETTINGS" ] && echo -e "${GREEN}  ✓ settings.json 已加载${NC}"
[ -f "$CLAUDE_MD" ] && echo -e "${GREEN}  ✓ CLAUDE.md 已加载${NC}"
[ -f "$CLAUDE_MCP" ] && echo -e "${GREEN}  ✓ MCP 配置已加载${NC}"
[ -f "$CLAUDE_SHORTCUTS" ] && echo -e "${GREEN}  ✓ 快捷命令已加载${NC}"

if [ "$ENABLE_MCP" = true ]; then
    echo -e "${GREEN}  ✓ MCP 工具已启用${NC}"
fi

echo ""
echo -e "${YELLOW}[6/6] 启动 Claude Code...${NC}"
echo ""

FULL_MODEL="${MODEL_PREFIX}${MODEL}"

CLAUDE_OPTS="--bare --dangerously-skip-permissions"

if [ "$MODE" = "interactive" ]; then
    echo -e "${CYAN}进入交互模式 (Ctrl+D 退出)${NC}"
    echo -e "${CYAN}使用模型: $FULL_MODEL${NC}"
    echo ""
    cd "$PROJECT_DIR" && claude $CLAUDE_OPTS --model "$FULL_MODEL"
elif [ "$MODE" = "print" ]; then
    if [ -n "$RESUME" ]; then
        cd "$PROJECT_DIR" && claude $CLAUDE_OPTS -p "$TASK" $RESUME --max-turns $MAX_TURNS --model "$FULL_MODEL" --output-format json
    elif [ -n "$CONTINUE" ]; then
        cd "$PROJECT_DIR" && claude $CLAUDE_OPTS -p "$TASK" --continue --max-turns $MAX_TURNS --model "$FULL_MODEL" --output-format json
    else
        cd "$PROJECT_DIR" && claude -p "$TASK" --max-turns $MAX_TURNS --model "$FULL_MODEL" --output-format json
    fi
fi

echo ""
echo -e "${GREEN}会话结束${NC}"