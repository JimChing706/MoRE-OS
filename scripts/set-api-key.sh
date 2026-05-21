#!/usr/bin/env bash

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env.local"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -s, --set KEY    设置 API Key"
    echo "  -g, --get       显示当前 API Key (隐藏部分)"
    echo "  -c, --check     检查 API Key 是否有效"
    echo "  -r, --remove    移除 API Key"
    echo "  -h, --help      显示帮助"
    echo ""
    echo "示例:"
    echo "  $0 -s sk-ant-api03-xxx  # 设置 API Key"
    echo "  $0 -g                   # 查看当前 Key"
    echo "  $0 -c                   # 验证 Key 是否有效"
    echo "  $0 -r                   # 移除 Key"
}

set_api_key() {
    local key="$1"

    if [ -z "$key" ]; then
        echo -e "${RED}错误: 请提供 API Key${NC}"
        echo "  获取 API Key: https://console.anthropic.com/settings/keys"
        exit 1
    fi

    echo "ANTHROPIC_API_KEY=$key" > "$ENV_FILE"
    echo -e "${GREEN}✓ API Key 已保存到 $ENV_FILE${NC}"
    echo ""
    echo -e "${YELLOW}使用方式:${NC}"
    echo "  source $ENV_FILE"
    echo "  或者在运行脚本前先: source $ENV_FILE"
}

get_api_key() {
    if [ -f "$ENV_FILE" ]; then
        local key=$(grep "ANTHROPIC_API_KEY=" "$ENV_FILE" | cut -d'=' -f2)
        if [ -n "$key" ]; then
            local masked="${key:0:8}...${key: -8}"
            echo -e "当前 API Key: ${GREEN}$masked${NC}"
        else
            echo -e "未设置 API Key"
        fi
    else
        echo -e "${YELLOW}未找到 API Key 配置文件${NC}"
    fi
}

check_api_key() {
    if [ -f "$ENV_FILE" ]; then
        source "$ENV_FILE"
    fi

    if [ -z "$ANTHROPIC_API_KEY" ]; then
        echo -e "${RED}错误: ANTHROPIC_API_KEY 未设置${NC}"
        echo "  使用 $0 -s <key> 设置"
        exit 1
    fi

    echo -e "${BLUE}检查 API Key...${NC}"

    local response=$(curl -s --max-time 10 \
        -H "x-api-key: $ANTHROPIC_API_KEY" \
        -H "anthropic-version: 2023-06-01" \
        "https://api.anthropic.com/v1/models" 2>&1)

    if echo "$response" | grep -q "api_key"; then
        echo -e "${RED}✗ API Key 无效${NC}"
        echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',{}).get('message',''))" 2>/dev/null || echo "$response"
        return 1
    elif echo "$response" | grep -q "claude"; then
        echo -e "${GREEN}✓ API Key 有效${NC}"
        return 0
    else
        echo -e "${YELLOW}? 无法确定 API Key 状态${NC}"
        echo "$response"
        return 1
    fi
}

remove_api_key() {
    if [ -f "$ENV_FILE" ]; then
        rm "$ENV_FILE"
        echo -e "${GREEN}✓ API Key 已移除${NC}"
    else
        echo -e "${YELLOW}未找到 API Key 配置文件${NC}"
    fi
}

COMMAND="${1:-help}"

case "$COMMAND" in
    -s|--set)
        set_api_key "$2"
        ;;
    -g|--get)
        get_api_key
        ;;
    -c|--check)
        check_api_key
        ;;
    -r|--remove)
        remove_api_key
        ;;
    -h|--help|help)
        show_help
        ;;
    *)
        echo -e "${RED}未知命令: $COMMAND${NC}"
        show_help
        ;;
esac