#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

LMSTUDIO_URL="http://localhost:1234/v1"

check_lmstudio() {
    if curl -s --max-time 2 "$LMSTUDIO_URL/models" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

get_models() {
    curl -s "$LMSTUDIO_URL/models" | python3 -c "
import sys,json
models = json.load(sys.stdin).get('data',[])
for m in models:
    print(m['id'])
" 2>/dev/null
}

chat() {
    local model="$1"
    local message="$2"

    curl -s "$LMSTUDIO_URL/chat/completions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer dummy-key" \
        -d "{\"model\": \"$model\", \"messages\": [{\"role\": \"user\", \"content\": \"$message\"}], \"temperature\": 0.7, \"max_tokens\": 2000}" | python3 -c "
import sys,json
try:
    result = json.load(sys.stdin)
    if 'choices' in result and len(result['choices']) > 0:
        print(result['choices'][0]['message'].get('content', ''))
    else:
        print('错误: 无响应')
except Exception as e:
    print(f'错误: {e}')
" 2>/dev/null
}

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}  本地模型聊天工具 (LM Studio)${NC}"
echo -e "${BLUE}==============================================${NC}"
echo ""

if ! check_lmstudio; then
    echo -e "${RED}错误: LM Studio 未运行或未加载模型${NC}"
    echo "请打开 LM Studio 并加载模型后重试"
    exit 1
fi

echo -e "${GREEN}✓ LM Studio 已连接${NC}"
echo ""

MODELS=($(get_models))

if [ ${#MODELS[@]} -eq 0 ]; then
    echo -e "${RED}错误: 未找到可用模型${NC}"
    exit 1
fi

echo "可用模型:"
for i in "${!MODELS[@]}"; do
    echo "  [$i] ${MODELS[$i]}"
done
echo ""

MODEL_INDEX=0
if [ $# -gt 0 ]; then
    MODEL_INDEX=$1
fi

if [ "$MODEL_INDEX" -ge 0 ] && [ "$MODEL_INDEX" -lt ${#MODELS[@]} ]; then
    MODEL="${MODELS[$MODEL_INDEX]}"
else
    MODEL="${MODELS[0]}"
fi

echo -e "使用模型: ${CYAN}$MODEL${NC}"
echo ""
echo -e "${YELLOW}输入消息开始对话，输入 'quit' 或 'exit' 退出${NC}"
echo ""

while true; do
    echo -n -e "${GREEN}>${NC} "
    read -r message

    if [ "$message" = "quit" ] || [ "$message" = "exit" ]; then
        echo -e "${YELLOW}再见!${NC}"
        break
    fi

    if [ -n "$message" ]; then
        echo ""
        chat "$MODEL" "$message"
        echo ""
    fi
done