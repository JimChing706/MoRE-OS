#!/usr/bin/env bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

show_help() {
    echo "用法: $0 [选项] [任务描述]"
    echo ""
    echo "选项:"
    echo "  -h, --help              显示帮助"
    echo "  -p, --provider PROVIDER 指定模型平台 (lmstudio|ollama)"
    echo "  -m, --model MODEL      指定模型名称"
    echo "  -c, --chat             交互式聊天模式"
    echo "  -f, --file FILE        分析指定文件"
    echo ""
    echo "示例:"
    echo "  $0 -p lmstudio '解释 main.py'"
    echo "  $0 -p ollama '修复这个bug'"
    echo "  $0 --chat"
}

PROVIDER=""
MODEL=""
MODE="single"
TARGET_FILE=""
CHAT_MODE=false

args=()
while [[ $# -gt 0 ]]; do
    case "$1" in
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
        -c|--chat)
            CHAT_MODE=true
            shift
            ;;
        -f|--file)
            TARGET_FILE="$2"
            shift 2
            ;;
        *)
            args+=("$1")
            shift
            ;;
    esac
done

set -- "${args[@]}"
TASK="$*"

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}  本地大模型 AI 助手 (完全离线)${NC}"
echo -e "${BLUE}==============================================${NC}"
echo ""

echo -e "${YELLOW}[1/4] 检测本地模型平台...${NC}"

LMSTUDIO_AVAILABLE=false
OLLAMA_AVAILABLE=false

if curl -s --max-time 2 "http://localhost:1234/v1/models" >/dev/null 2>&1; then
    LMSTUDIO_AVAILABLE=true
    echo -e "  ✓ LM Studio: ${GREEN}运行中 (端口 1234)${NC}"
fi

if curl -s --max-time 2 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
    OLLAMA_AVAILABLE=true
    echo -e "  ✓ Ollama:   ${GREEN}运行中 (端口 11434)${NC}"
fi

if [ -z "$PROVIDER" ]; then
    if [ "$LMSTUDIO_AVAILABLE" = true ]; then
        PROVIDER="lmstudio"
    elif [ "$OLLAMA_AVAILABLE" = true ]; then
        PROVIDER="ollama"
    else
        echo -e "${RED}错误: 没有可用的本地模型平台${NC}"
        exit 1
    fi
fi

echo "  使用平台: $PROVIDER"

echo ""
echo -e "${YELLOW}[2/4] 配置模型...${NC}"

if [ -z "$MODEL" ]; then
    case "$PROVIDER" in
        lmstudio)
            MODEL="qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled"
            ;;
        ollama)
            MODEL="qwen2.5:7b"
            ;;
    esac
fi

echo "  模型: $MODEL"

echo ""
echo -e "${YELLOW}[3/4] 准备请求...${NC}"

if [ -n "$TARGET_FILE" ]; then
    if [ -f "$TARGET_FILE" ]; then
        FILE_CONTENT=$(cat "$TARGET_FILE")
        TASK="$TASK

文件内容 ($TARGET_FILE):
$FILE_CONTENT"
        echo "  ✓ 已加载文件: $TARGET_FILE"
    else
        echo -e "${RED}错误: 文件不存在: $TARGET_FILE${NC}"
        exit 1
    fi
fi

if [ -z "$TASK" ]; then
    if [ "$CHAT_MODE" = true ]; then
        echo "  进入聊天模式..."
    else
        echo -e "${RED}错误: 请提供任务描述${NC}"
        show_help
        exit 1
    fi
fi

echo ""
echo -e "${YELLOW}[4/4] 调用本地模型...${NC}"
echo ""

call_lmstudio() {
    local prompt="$1"
    curl -s --max-time 300 "http://localhost:1234/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"$prompt\"}], \"stream\": false}" \
        | python3 -c "
import sys,json
try:
    data=json.load(sys.stdin)
    if 'choices' in data and len(data['choices']) > 0:
        print(data['choices'][0]['message']['content'])
    else:
        print(data)
except Exception as e: print('Error:', e)
"
}

call_ollama() {
    local prompt="$1"
    curl -s --max-time 300 "http://localhost:11434/api/chat" \
        -H "Content-Type: application/json" \
        -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"$prompt\"}], \"stream\": false}" \
        | python3 -c "
import sys,json
try:
    data=json.load(sys.stdin)
    print(data.get('message', {}).get('content', ''))
except Exception as e: print('Error:', e)
"
}

if [ "$CHAT_MODE" = true ]; then
    echo -e "${CYAN}进入聊天模式 (输入 'exit' 退出)${NC}"
    echo ""

    while true; do
        echo -n -e "${GREEN}> ${NC}"
        read -r user_input

        if [ "$user_input" = "exit" ] || [ "$user_input" = "quit" ]; then
            echo "退出聊天"
            break
        fi

        if [ -z "$user_input" ]; then
            continue
        fi

        echo -e "${CYAN}"
        if [ "$PROVIDER" = "lmstudio" ]; then
            call_lmstudio "$user_input"
        else
            call_ollama "$user_input"
        fi
        echo -e "${NC}"
    done
else
    if [ "$PROVIDER" = "lmstudio" ]; then
        call_lmstudio "$TASK"
    else
        call_ollama "$TASK"
    fi
fi

echo ""
echo -e "${GREEN}完成${NC}"