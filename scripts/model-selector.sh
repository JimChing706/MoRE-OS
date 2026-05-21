#!/usr/bin/env bash

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LMSTUDIO_MODELS=()
OLLAMA_MODELS=()

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

scan_models() {
    if curl -s --max-time 3 "http://localhost:1234/v1/models" >/dev/null 2>&1; then
        local response=$(curl -s "http://localhost:1234/v1/models")
        LMSTUDIO_MODELS=($(echo "$response" | python3 -c "import sys,json; print(' '.join([m['id'] for m in json.load(sys.stdin).get('data',[])]))" 2>/dev/null))
    fi

    if curl -s --max-time 3 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
        local response=$(curl -s "http://localhost:11434/api/tags")
        OLLAMA_MODELS=($(echo "$response" | python3 -c "import sys,json; print(' '.join([m['name'] for m in json.load(sys.stdin).get('models',[])]))" 2>/dev/null))
    fi
}

TASK_TYPES=(
    "reasoning:推理分析:需要深度思考和逻辑推理的任务"
    "coding:代码开发:编程、调试、重构"
    "writing:写作创作:文档、报告、内容创作"
    "general:通用对话:日常问答和信息查询"
    "analysis:数据分析:统计、图表、数据处理"
    "review:代码审查:代码审查和安全检查"
)

select_model_by_task() {
    local task_type="$1"
    local task_desc="$2"

    case "$task_type" in
        reasoning)
            for m in "${LMSTUDIO_MODELS[@]}"; do
                if [[ "$m" == *"qwen"* ]] || [[ "$m" == *"reasoning"* ]]; then
                    echo "lmstudio/$m"
                    return
                fi
            done
            echo "lmstudio/${LMSTUDIO_MODELS[0]:-qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled}"
            ;;
        coding)
            for m in "${LMSTUDIO_MODELS[@]}"; do
                if [[ "$m" == *"code"* ]] || [[ "$m" == *"coder"* ]]; then
                    echo "lmstudio/$m"
                    return
                fi
            done
            echo "lmstudio/${LMSTUDIO_MODELS[0]:-qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled}"
            ;;
        writing)
            for m in "${LMSTUDIO_MODELS[@]}"; do
                if [[ "$m" == *"instruct"* ]] || [[ "$m" == *"chat"* ]]; then
                    echo "lmstudio/$m"
                    return
                fi
            done
            echo "lmstudio/${LMSTUDIO_MODELS[0]:-qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled}"
            ;;
        analysis)
            for m in "${OLLAMA_MODELS[@]}"; do
                if [[ "$m" == *"math"* ]] || [[ "$m" == *"code"* ]]; then
                    echo "ollama/$m"
                    return
                fi
            done
            echo "ollama/${OLLAMA_MODELS[0]:-qwen2.5:7b}"
            ;;
        review)
            for m in "${LMSTUDIO_MODELS[@]}"; do
                if [[ "$m" == *"claude"* ]] || [[ "$m" == *"opus"* ]]; then
                    echo "lmstudio/$m"
                    return
                fi
            done
            echo "lmstudio/${LMSTUDIO_MODELS[0]:-qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled}"
            ;;
        *)
            if [ ${#LMSTUDIO_MODELS[@]} -gt 0 ]; then
                echo "lmstudio/${LMSTUDIO_MODELS[0]}"
            else
                echo "ollama/${OLLAMA_MODELS[0]:-qwen2.5:7b}"
            fi
            ;;
    esac
}

analyze_task() {
    local task="$1"
    local lower_task=$(echo "$task" | tr '[:upper:]' '[:lower:]')

    if [[ "$lower_task" == *"推理"* ]] || [[ "$lower_task" == *"reason"* ]] || [[ "$lower_task" == *"证明"* ]] || [[ "$lower_task" == *"思考"* ]]; then
        echo "reasoning"
    elif [[ "$lower_task" == *"代码"* ]] || [[ "$lower_task" == *"code"* ]] || [[ "$lower_task" == *"编程"* ]] || [[ "$lower_task" == *"debug"* ]] || [[ "$lower_task" == *"修复"* ]] || [[ "$lower_task" == *"实现"* ]]; then
        echo "coding"
    elif [[ "$lower_task" == *"写"* ]] || [[ "$lower_task" == *"文档"* ]] || [[ "$lower_task" == *"报告"* ]] || [[ "$lower_task" == *"文章"* ]]; then
        echo "writing"
    elif [[ "$lower_task" == *"分析"* ]] || [[ "$lower_task" == *"统计"* ]] || [[ "$lower_task" == *"数据"* ]]; then
        echo "analysis"
    elif [[ "$lower_task" == *"审查"* ]] || [[ "$lower_task" == *"review"* ]] || [[ "$lower_task" == *"检查"* ]] || [[ "$lower_task" == *"安全"* ]]; then
        echo "review"
    else
        echo "general"
    fi
}

show_help() {
    echo "用法: $0 [选项] [任务描述]"
    echo ""
    echo "选项:"
    echo "  -h, --help              显示帮助"
    echo "  -t, --type TYPE         任务类型 (reasoning|coding|writing|general|analysis|review)"
    echo "  -a, --auto              自动分析任务类型"
    echo "  -l, --list              列出可用模型"
    echo "  -s, --show              显示当前推荐模型"
    echo ""
    echo "示例:"
    echo "  $0 -t coding '帮我写一个排序算法'"
    echo "  $0 -a '分析这个数据文件'"
    echo "  $0 --list"
}

TYPE="auto"
TASK=""
LIST_MODELS=false
SHOW_RECOMMEND=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -t|--type)
            TYPE="$2"
            shift 2
            ;;
        -a|--auto)
            TYPE="auto"
            shift
            ;;
        -l|--list)
            LIST_MODELS=true
            shift
            ;;
        -s|--show)
            SHOW_RECOMMEND=true
            shift
            ;;
        *)
            TASK="$1"
            shift
            ;;
    esac
done

scan_models

if [ "$LIST_MODELS" = true ]; then
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  可用模型列表${NC}"
    echo -e "${BLUE}==============================================${NC}"
    echo ""
    echo -e "${GREEN}LM Studio (端口 1234):${NC}"
    for m in "${LMSTUDIO_MODELS[@]}"; do
        echo "  - $m"
    done
    if [ ${#LMSTUDIO_MODELS[@]} -eq 0 ]; then
        echo "  (无可用模型)"
    fi
    echo ""
    echo -e "${GREEN}Ollama (端口 11434):${NC}"
    for m in "${OLLAMA_MODELS[@]}"; do
        echo "  - $m"
    done
    if [ ${#OLLAMA_MODELS[@]} -eq 0 ]; then
        echo "  (无可用模型)"
    fi
    exit 0
fi

if [ "$SHOW_RECOMMEND" = true ]; then
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  任务类型推荐模型${NC}"
    echo -e "${BLUE}==============================================${NC}"
    echo ""
    for item in "${TASK_TYPES[@]}"; do
        IFS=':' read -r key desc <<< "$item"
        model=$(select_model_by_task "$key" "")
        echo -e "${CYAN}$key${NC} ($desc)"
        echo -e "  推荐: ${GREEN}$model${NC}"
        echo ""
    done
    exit 0
fi

if [ -n "$TASK" ]; then
    if [ "$TYPE" = "auto" ]; then
        TYPE=$(analyze_task "$TASK")
    fi

    case "$TYPE" in
        reasoning) task_desc="推理分析" ;;
        coding) task_desc="代码开发" ;;
        writing) task_desc="写作创作" ;;
        general) task_desc="通用对话" ;;
        analysis) task_desc="数据分析" ;;
        review) task_desc="代码审查" ;;
        *) task_desc="通用任务" ;;
    esac

    MODEL=$(select_model_by_task "$TYPE" "$TASK")

    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  智能模型选择${NC}"
    echo -e "${BLUE}==============================================${NC}"
    echo ""
    echo -e "任务类型: ${CYAN}$task_desc${NC}"
    echo -e "任务描述: ${YELLOW}$TASK${NC}"
    echo ""
    echo -e "推荐模型: ${GREEN}$MODEL${NC}"
    echo ""
    echo -e "运行命令:"
    echo -e "  ${CYAN}claude -p \"$TASK\" --model \"$MODEL\"${NC}"
fi