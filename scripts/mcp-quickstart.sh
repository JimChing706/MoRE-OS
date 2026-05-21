#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$PROJECT_DIR/.claude/mcp"

echo "=============================================="
echo "  MCP 工具快速安装"
echo "=============================================="
echo ""

install_mcp() {
    local name="$1"
    local package="$2"

    echo -n "安装 $name... "
    if npm list -g "$package" >/dev/null 2>&1; then
        echo "已安装"
    else
        npm install -g "$package" 2>/dev/null && echo "完成" || echo "失败"
    fi
}

echo "安装核心 MCP 服务器..."
install_mcp "文件系统" "@modelcontextprotocol/server-filesystem"
install_mcp "Git" "@modelcontextprotocol/server-git"
install_mcp "网页抓取" "@modelcontextprotocol/server-fetch"
install_mcp "知识图谱" "@modelcontextprotocol/server-memory"
install_mcp "浏览器" "@modelcontextprotocol/server-puppeteer"
install_mcp "搜索" "@modelcontextprotocol/server-brave-search"

echo ""
echo "可选: 设置环境变量"
echo "  export BRAVE_API_KEY=你的密钥  # 启用搜索"
echo ""
echo "配置已保存至: $MCP_DIR/servers.json"