#!/usr/bin/env bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}  Claude Code 本地大模型深度个性化配置${NC}"
echo -e "${BLUE}        (LM Studio + Ollama 双平台)${NC}"
echo -e "${BLUE}==============================================${NC}"
echo ""

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="$PROJECT_DIR/.claude"

mkdir -p "$CLAUDE_DIR"

echo -e "${YELLOW}[1/6] 检测本地模型平台...${NC}"

LMSTUDIO_AVAILABLE=false
OLLAMA_AVAILABLE=false

if curl -s --max-time 3 "http://localhost:1234/v1/models" >/dev/null 2>&1; then
    LMSTUDIO_AVAILABLE=true
    echo -e "  ✓ LM Studio: ${GREEN}运行中 (端口 1234)${NC}"
else
    echo -e "  ✗ LM Studio: ${YELLOW}未运行${NC}"
    echo "    提示: 打开 LM Studio 并加载模型以启用"
fi

if curl -s --max-time 3 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
    OLLAMA_AVAILABLE=true
    echo -e "  ✓ Ollama:   ${GREEN}运行中 (端口 11434)${NC}"
else
    echo -e "  ✗ Ollama:   ${YELLOW}未运行${NC}"
    echo "    提示: 运行 'ollama serve' 启动"
fi

echo ""

echo -e "${YELLOW}[2/6] 扫描可用模型...${NC}"

if [ "$LMSTUDIO_AVAILABLE" = true ]; then
    echo -e "  ${GREEN}LM Studio 模型:${NC}"
    curl -s "http://localhost:1234/v1/models" | python3 -c "
import sys,json
for m in json.load(sys.stdin).get('data',[]):
    print(f'    - {m[\"id\"]}')" 2>/dev/null
fi

if [ "$OLLAMA_AVAILABLE" = true ]; then
    echo -e "  ${GREEN}Ollama 模型:${NC}"
    curl -s "http://localhost:11434/api/tags" | python3 -c "
import sys,json
for m in json.load(sys.stdin).get('models',[]):
    print(f'    - {m[\"name\"]}')" 2>/dev/null
fi

echo ""

echo -e "${YELLOW}[3/6] 创建 Claude Code 配置...${NC}"

cat > "$CLAUDE_DIR/settings.json" << 'EOF'
{
  "model": {
    "preference": "local",
    "localProviders": {
      "lmstudio": {
        "name": "LM Studio",
        "endpoint": "http://localhost:1234/v1",
        "defaultModel": "qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled",
        "apiType": "openai-compatible"
      },
      "ollama": {
        "name": "Ollama",
        "endpoint": "http://localhost:11434",
        "defaultModel": "qwen2.5:7b",
        "apiType": "openai-compatible"
      }
    },
    "fallback": "claude-sonnet-4-6"
  },
  "permissions": {
    "allow": [
      "Bash",
      "Bash(git *)",
      "Bash(npm run *)",
      "Bash(python *)",
      "Read",
      "Edit",
      "Write",
      "WebSearch",
      "WebFetch"
    ],
    "ask": ["Write(*.sh)", "Bash(rm *)"],
    "deny": ["Bash(rm -rf /*)", "Read(.env)"]
  },
  "env": {
    "LM_STUDIO_HOST": "http://localhost:1234/v1",
    "OLLAMA_HOST": "http://localhost:11434"
  },
  "hooks": {
    "PostToolUse": [
      {"matcher": "Write(*.py)", "hooks": [{"type": "command", "command": "ruff check --fix $CLAUDE_FILE_PATHS 2>/dev/null || true"}]},
      {"matcher": "Write(*.{ts,tsx,js,jsx})", "hooks": [{"type": "command", "command": "prettier --write $CLAUDE_FILE_PATHS 2>/dev/null || true"}]}
    ]
  }
}
EOF

echo -e "${GREEN}  ✓ settings.json 已创建${NC}"

echo ""
echo -e "${YELLOW}[4/6] 创建 CLAUDE.md 项目记忆...${NC}"

cat > "$CLAUDE_DIR/CLAUDE.md" << 'EOF'
# QNMing MoRE OS - Claude Code 配置

## 本地模型配置 (双平台)

### LM Studio (推荐 - 性能更强)
- 端点: http://localhost:1234/v1
- 默认: qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled

### Ollama (轻量备用)
- 端点: http://localhost:11434
- 默认: qwen2.5:7b

### 回退
- claude-sonnet-4-6

## 调用方式
```bash
./scripts/claude-local-run.sh --provider lmstudio "任务"
./scripts/claude-local-run.sh --provider ollama "任务"
./scripts/claude-local-run.sh --interactive
```

## 代码规范
- Python: 4空格, 类型提示
- TypeScript: 2空格, 严格模式

## 常用命令
- 启动后端: more-os serve --port 8001
- 启动前端: cd app && npm run dev
- Claude Code: ./scripts/claude-local-run.sh --print "任务"
EOF

echo -e "${GREEN}  ✓ CLAUDE.md 已创建${NC}"

echo ""
echo -e "${YELLOW}[5/6] 创建自定义子代理...${NC}"

mkdir -p "$CLAUDE_DIR/agents"

cat > "$CLAUDE_DIR/agents/more-os-expert.md" << 'EOF'
---
name: more-os-expert
description: MoRE OS 系统专家，专注于架构和实现
model: sonnet
tools: [Read, Edit, Write, Bash]
---
你是 MoRE OS 系统的专家。熟悉:
- more_core 核心架构
- Agent 编排和工作流
- MCP 工具集成
- API 服务开发

提供高质量的代码建议和架构指导。
EOF

cat > "$CLAUDE_DIR/agents/code-reviewer.md" << 'EOF'
---
name: code-reviewer
description: 代码审查专家，专注于质量和安全
model: sonnet
tools: [Read, Bash]
---
你是代码审查专家。检查:
- 代码质量和风格
- 安全漏洞
- 性能问题
- 测试覆盖率

提供具体的改进建议。
EOF

echo -e "${GREEN}  ✓ 子代理配置完成 (more-os-expert, code-reviewer)${NC}"

echo ""
echo -e "${YELLOW}[6/6] 创建一键启动脚本...${NC}"

if [ -f "$PROJECT_DIR/scripts/claude-local-run.sh" ]; then
    echo -e "${GREEN}  ✓ claude-local-run.sh 已存在${NC}"
else
    cat > "$PROJECT_DIR/scripts/claude-local-run.sh" << 'RUNEOF'
#!/usr/bin/env bash
# 一键启动脚本 - 见 scripts/claude-local-run.sh 完整版本
echo "请运行完整的 claude-local-run.sh 脚本"
RUNEOF
    chmod +x "$PROJECT_DIR/scripts/claude-local-run.sh"
    echo -e "${GREEN}  ✓ claude-local-run.sh 已创建${NC}"
fi

echo ""
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}  配置完成!${NC}"
echo -e "${GREEN}==============================================${NC}"
echo ""
echo "配置文件位置: $CLAUDE_DIR"
echo "  - settings.json    (Claude Code 设置)"
echo "  - CLAUDE.md       (项目记忆)"
echo "  - agents/         (自定义子代理)"
echo ""
echo "一键启动:"
echo "  ./scripts/claude-local-run.sh --print '你的任务'"
echo "  ./scripts/claude-local-run.sh --interactive"
echo "  ./scripts/claude-local-run.sh --provider lmstudio '任务'"
echo "  ./scripts/claude-local-run.sh --provider ollama '任务'"
echo ""