#!/usr/bin/env bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

show_help() {
    echo "用法: $0 [选项] [任务]"
    echo ""
    echo "选项:"
    echo "  -h, --help              显示帮助"
    echo "  -m, --method METHOD     使用方式:"
    echo "                          cli       - 直接调用本地模型 (推荐)"
    echo "                          windsurf  - 打开 Windsurf AI IDE"
    echo "                          vscode    - 打开 VS Code + Continue"
    echo "                          chat      - 交互式聊天"
    echo "  -p, --provider PROVIDER 模型平台 (lmstudio|ollama|auto)"
    echo "  -t, --task TASK         任务描述"
    echo ""
    echo "示例:"
    echo "  $0 -m cli -t '解释 main.py'"
    echo "  $0 -m windsurf"
    echo "  $0 -m vscode"
    echo "  $0 -m chat -p lmstudio"
}

check_services() {
    echo -e "${YELLOW}检测本地服务...${NC}"

    if curl -s --max-time 2 "http://localhost:1234/v1/models" >/dev/null 2>&1; then
        echo -e "  ✓ LM Studio: ${GREEN}运行中 (端口 1234)${NC}"
        LMSTUDIO_OK=true
    else
        echo -e "  ✗ LM Studio: ${YELLOW}未运行${NC}"
        echo "    启动: 打开 LM Studio 应用"
        LMSTUDIO_OK=false
    fi

    if curl -s --max-time 2 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
        echo -e "  ✓ Ollama:   ${GREEN}运行中 (端口 11434)${NC}"
        OLLAMA_OK=true
    else
        echo -e "  ✗ Ollama:   ${YELLOW}未运行${NC}"
        echo "    启动: ollama serve"
        OLLAMA_OK=false
    fi

    if [ "$LMSTUDIO_OK" = false ] && [ "$OLLAMA_OK" = false ]; then
        echo -e "\n${RED}错误: 没有可用的本地模型服务${NC}"
        echo "请启动 LM Studio 或 Ollama 后重试"
        exit 1
    fi
}

METHOD="cli"
PROVIDER="auto"
TASK=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -m|--method)
            METHOD="$2"
            shift 2
            ;;
        -p|--provider)
            PROVIDER="$2"
            shift 2
            ;;
        -t|--task)
            TASK="$2"
            shift 2
            ;;
        *)
            TASK="$1"
            shift
            ;;
    esac
done

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}  本地 AI 编程助手 (完全离线)${NC}"
echo -e "${BLUE}==============================================${NC}"
echo ""

check_services

echo ""
echo -e "${YELLOW}启动方式: $METHOD${NC}"

case "$METHOD" in
    cli)
        if [ -z "$TASK" ]; then
            echo -e "${RED}错误: 请提供任务描述 (-t '任务')${NC}"
            exit 1
        fi
        echo ""
        bash "$PROJECT_DIR/scripts/local-ai.sh" -p "$PROVIDER" -m "$TASK"
        ;;

    windsurf)
        echo ""
        echo -e "${CYAN}启动 Windsurf...${NC}"
        echo "  配置: $PROJECT_DIR/.vscode/continue/config.json"
        open -a Windsurf "$PROJECT_DIR"
        ;;

    vscode)
        echo ""
        echo -e "${CYAN}启动 VS Code...${NC}"
        echo "  配置: $PROJECT_DIR/.vscode/continue/config.json"
        echo "  插件: Continue.dev (请在 VS Code 中安装)"
        code "$PROJECT_DIR" 2>/dev/null || open -a "Visual Studio Code" "$PROJECT_DIR"
        ;;

    chat)
        echo ""
        bash "$PROJECT_DIR/scripts/local-ai.sh" -p "$PROVIDER" --chat
        ;;

    *)
        echo -e "${RED}错误: 未知方式 '$METHOD'${NC}"
        show_help
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}完成${NC}"