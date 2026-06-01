#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

show_help() {
    echo "用法: $0 [命令]"
    echo ""
    echo "开发工作流命令:"
    echo "  lint         - 运行代码检查 (ruff)"
    echo "  format       - 格式化代码"
    echo "  typecheck    - 类型检查 (mypy)"
    echo "  test         - 运行测试 (pytest)"
    echo "  pre-commit   - 完整的提交前检查"
    echo "  clean        - 清理缓存文件"
    echo "  all          - 运行所有检查"
    echo ""
}

run_lint() {
    echo -e "${BLUE}[Lint] 运行代码检查...${NC}"
    cd "$PROJECT_DIR"
    ruff check . --fix 2>/dev/null || true
    echo -e "${GREEN}✓ Lint 完成${NC}"
}

run_format() {
    echo -e "${BLUE}[Format] 格式化代码...${NC}"
    cd "$PROJECT_DIR"
    ruff format . 2>/dev/null || true
    echo -e "${GREEN}✓ Format 完成${NC}"
}

run_typecheck() {
    echo -e "${BLUE}[TypeCheck] 类型检查...${NC}"
    cd "$PROJECT_DIR"
    mypy . --ignore-missing-imports 2>/dev/null || true
    echo -e "${GREEN}✓ TypeCheck 完成${NC}"
}

run_test() {
    echo -e "${BLUE}[Test] 运行测试...${NC}"
    cd "$PROJECT_DIR"
    pytest -v --tb=short 2>/dev/null || true
    echo -e "${GREEN}✓ Test 完成${NC}"
}

run_clean() {
    echo -e "${BLUE}[Clean] 清理缓存...${NC}"
    cd "$PROJECT_DIR"
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type f -name "*.pyo" -delete 2>/dev/null || true
    echo -e "${GREEN}✓ Clean 完成${NC}"
}

run_precommit() {
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}  Pre-Commit 检查${NC}"
    echo -e "${BLUE}==============================================${NC}"
    echo ""

    run_clean
    run_format
    run_lint
    run_typecheck
    run_test

    echo ""
    echo -e "${GREEN}==============================================${NC}"
    echo -e "${GREEN}  Pre-Commit 检查完成!${NC}"
    echo -e "${GREEN}==============================================${NC}"
}

COMMAND="${1:-help}"

case "$COMMAND" in
    lint)
        run_lint
        ;;
    format)
        run_format
        ;;
    typecheck)
        run_typecheck
        ;;
    test)
        run_test
        ;;
    pre-commit)
        run_precommit
        ;;
    clean)
        run_clean
        ;;
    all)
        run_precommit
        ;;
    *)
        show_help
        ;;
esac