#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_DIR="$PROJECT_DIR/.claude/sessions"
mkdir -p "$SESSION_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

list_sessions() {
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  会话历史${NC}"
    echo -e "${BLUE}==============================================${NC}"
    echo ""

    local sessions=($(ls -t "$SESSION_DIR" 2>/dev/null))

    if [ ${#sessions[@]} -eq 0 ]; then
        echo "暂无会话记录"
        return
    fi

    local i=1
    for session in "${sessions[@]}"; do
        local name="${session%.json}"
        local info=$(cat "$SESSION_DIR/$session" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f\"{d.get('task','')[:40]} | {d.get('model','')} | {d.get('timestamp','')}\")
" 2>/dev/null || echo "未知")
        echo -e "  [$i] $name"
        echo -e "      $info"
        ((i++))
    done

    echo ""
    echo "使用说明:"
    echo "  $0 resume <会话名>  - 恢复会话"
    echo "  $0 delete <会话名>  - 删除会话"
    echo "  $0 clear           - 清理所有会话"
}

save_session() {
    local name="$1"
    local task="$2"
    local model="$3"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    cat > "$SESSION_DIR/${name}.json" << EOF
{
  "name": "$name",
  "task": "$task",
  "model": "$model",
  "timestamp": "$timestamp",
  "project": "$PROJECT_DIR"
}
EOF

    echo -e "${GREEN}✓ 会话已保存: $name${NC}"
}

resume_session() {
    local name="$1"

    if [ ! -f "$SESSION_DIR/${name}.json" ]; then
        echo -e "${RED}错误: 会话不存在${NC}"
        return 1
    fi

    local info=$(cat "$SESSION_DIR/${name}.json" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(d.get('task',''))
print(d.get('model',''))
" 2>/dev/null)

    local task=$(echo "$info" | head -1)
    local model=$(echo "$info" | tail -1)

    echo -e "${BLUE}恢复会话: $name${NC}"
    echo -e "任务: ${CYAN}$task${NC}"
    echo -e "模型: ${GREEN}$model${NC}"
    echo ""

    cd "$PROJECT_DIR" && claude -p "继续之前的任务: $task" --model "$model" --continue
}

delete_session() {
    local name="$1"

    if [ ! -f "$SESSION_DIR/${name}.json" ]; then
        echo -e "${RED}错误: 会话不存在${NC}"
        return 1
    fi

    rm "$SESSION_DIR/${name}.json"
    echo -e "${GREEN}✓ 会话已删除: $name${NC}"
}

clear_sessions() {
    rm -f "$SESSION_DIR"/*.json
    echo -e "${GREEN}✓ 已清理所有会话${NC}"
}

show_help() {
    echo "用法: $0 [命令] [参数]"
    echo ""
    echo "命令:"
    echo "  list                列出所有会话"
    echo "  save <名称> <任务>  保存当前会话"
    echo "  resume <名称>       恢复会话"
    echo "  delete <名称>       删除会话"
    echo "  clear               清理所有会话"
    echo ""
    echo "示例:"
    echo "  $0 list"
    echo "  $0 save bugfix-001 '修复登录问题'"
    echo "  $0 resume bugfix-001"
    echo "  $0 delete old-session"
}

COMMAND="${1:-list}"
NAME="${2:-}"
TASK="${3:-}"

case "$COMMAND" in
    list|ls)
        list_sessions
        ;;
    save)
        if [ -z "$NAME" ] || [ -z "$TASK" ]; then
            echo -e "${RED}错误: 需要提供会话名称和任务描述${NC}"
            show_help
            exit 1
        fi
        save_session "$NAME" "$TASK" "auto"
        ;;
    resume|restore)
        if [ -z "$NAME" ]; then
            echo -e "${RED}错误: 需要提供会话名称${NC}"
            show_help
            exit 1
        fi
        resume_session "$NAME"
        ;;
    delete|rm)
        if [ -z "$NAME" ]; then
            echo -e "${RED}错误: 需要提供会话名称${NC}"
            show_help
            exit 1
        fi
        delete_session "$NAME"
        ;;
    clear)
        clear_sessions
        ;;
    -h|--help|help)
        show_help
        ;;
    *)
        echo -e "${RED}未知命令: $COMMAND${NC}"
        show_help
        ;;
esac