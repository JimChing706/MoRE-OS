# QNMing MoRE OS 完整操作手册

> Claude Code + 本地大模型深度个性化配置方案

---

## 目录

1. [系统架构](#1-系统架构)
2. [快速启动](#2-快速启动)
3. [本地模型配置](#3-本地模型配置)
4. [Claude Code 集成](#4-claude-code-集成)
5. [一键启动方案](#5-一键启动方案)
6. [高级功能](#6-高级功能)
7. [故障排除](#7-故障排除)

---

## 1. 系统架构

### 1.1 组件概览

```
┌─────────────────────────────────────────────────────────────────┐
│                     QNMing MoRE OS                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │ 前端        │    │ 后端 API    │    │ Claude Code │        │
│  │ Dashboard   │◄──►│ (FastAPI)   │◄──►│ + 本地模型  │        │
│  │ :3002       │    │ :8001       │    │             │        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│                           │                    │             │
│                     ┌──────┴──────┐        ┌────┴────┐       │
│                     │ 本地模型    │        │ LM      │       │
│                     │ 运行平台    │        │ Studio  │       │
│                     └─────────────┘        │ Ollama  │       │
│                                         └─────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 端口分配

| 服务 | 端口 | 说明 |
|------|------|------|
| MoRE OS 后端 | 8001 | API 服务 |
| 前端 Dashboard | 3002 | Web 界面 |
| LM Studio | 1234 | 本地模型 API |
| Ollama | 11434 | 本地模型 API |

---

## 2. 快速启动

### 2.1 一键启动所有服务

```bash
cd /Users/qnming/AI_Cample/QNMing\ MoRE\ OS\ preVersion

# 启动后端
cd more_core && python3 -m more_core.cli serve --port 8001 &

# 启动前端
cd app && npm run dev &
```

### 2.2 使用一键启动菜单

```bash
# 交互式菜单
./run-local-ai.sh

# 快捷命令
./run-local-ai.sh status      # 查看状态
./run-local-ai.sh models      # 查看模型
./run-local-ai.sh chat        # 本地聊天
```

---

## 3. 本地模型配置

### 3.1 LM Studio 配置

1. **下载安装**: https://lmstudio.ai
2. **启动 LM Studio**
3. **下载模型**: 搜索并下载如 `qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled`
4. **加载模型**: 在 LM Studio 中点击加载模型
5. **验证**: 确保 `http://localhost:1234/v1/models` 可访问

### 3.2 Ollama 配置

```bash
# 安装 Ollama
brew install ollama

# 启动服务
ollama serve

# 下载模型
ollama pull qwen2.5:7b

# 验证
curl http://localhost:11434/api/tags
```

### 3.3 可用模型列表

**LM Studio (17个模型)**:
- `gemma-4-31b-it-claude-opus-distill-v2`
- `qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled`
- `gemma-4-26b-a4b-it-claude-opus-distill`
- `qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2`
- `qwen/qwen3.6-27b`
- `opus4.7-gods.ghost.codex-4b.gguf`
- 等等...

**Ollama (2个模型)**:
- `qwen2.5:7b`
- `aratan/qwen3.5-uncensored:9b`

---

## 4. Claude Code 集成

### 4.1 API Key 配置

**方式1: 环境变量**
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-local-proxy-key"
```

**方式2: 配置文件**
```bash
# 编辑 run-local-ai.sh 或 claude-local-run.sh
# 在文件开头添加:
export ANTHROPIC_API_KEY="sk-ant-api03-local-proxy-key"
```

### 4.2 使用 Claude Code 调用本地模型

```bash
# 使用 LM Studio
./scripts/claude-local-run.sh --provider lmstudio --print "你的任务"

# 使用 Ollama
./scripts/claude-local-run.sh --provider ollama --print "你的任务"

# 指定模型
./scripts/claude-local-run.sh --provider lmstudio --model "模型名" --print "任务"
```

### 4.3 常用 Claude Code 选项

```bash
# 交互模式
claude --bare --dangerously-skip-permissions --model lmstudio/模型名

# 单次任务
claude -p "任务描述" --max-turns 1 --model lmstudio/模型名

# 跳过权限检查
claude --dangerously-skip-permissions -p "任务"
```

---

## 5. 一键启动方案

### 5.1 主脚本功能

`run-local-ai.sh` 提供以下功能:

| 功能 | 菜单选项 | 快捷命令 |
|------|----------|----------|
| 交互模式 | [1] | `./run-local-ai.sh i` |
| 快速任务 | [2] | `./run-local-ai.sh t "任务"` |
| LM Studio | [3] | `./run-local-ai.sh lmstudio` |
| Ollama | [4] | `./run-local-ai.sh ollama` |
| API Key | [5] | `./run-local-ai.sh api` |
| 智能推荐 | [6] | - |
| 本地聊天 | [7] | `./run-local-ai.sh chat` |
| 会话管理 | [8] | - |
| API Key管理 | [9] | - |
| 配置环境 | [10] | - |
| 安装 MCP | [11] | - |
| 代码检查 | [12] | - |
| 模型查看 | [13] | `./run-local-ai.sh models` |
| 状态诊断 | [14] | `./run-local-ai.sh status` |

### 5.2 核心脚本说明

| 脚本 | 功能 |
|------|------|
| `run-local-ai.sh` | 主入口，一键启动菜单 |
| `scripts/claude-local-run.sh` | Claude Code 启动脚本 |
| `scripts/lmstudio-chat.py` | 本地模型聊天工具 |
| `scripts/local-chat.sh` | 交互式本地聊天 |
| `scripts/model-selector.sh` | 智能模型选择 |
| `scripts/session-manager.sh` | 会话管理 |
| `scripts/dev-workflow.sh` | 开发工作流 |
| `scripts/set-api-key.sh` | API Key 管理 |

### 5.3 使用示例

**场景1: 本地模型聊天**
```bash
./run-local-ai.sh chat
# 选择模型编号
# 输入消息开始对话
# 输入 quit 退出
```

**场景2: Claude Code 快速任务**
```bash
./run-local-ai.sh t "帮我写一个排序算法"
```

**场景3: 查看所有可用模型**
```bash
./run-local-ai.sh models
```

**场景4: 诊断服务状态**
```bash
./run-local-ai.sh status
```

---

## 6. 高级功能

### 6.1 MCP 工具配置

配置文件: `.claude/mcp/servers.json`

**已启用的 MCP 服务器**:
- `filesystem` - 文件系统访问
- `git` - Git 操作
- `fetch` - 网页抓取
- `memory` - 知识图谱

**可选 MCP 服务器** (需配置环境变量):
- `brave-search` - 网页搜索
- `puppeteer` - 浏览器自动化
- `sqlite` - SQLite 数据库
- `github` - GitHub 操作

### 6.2 提示词模板

| 模板 | 路径 | 用途 |
|------|------|------|
| 代码审查 | `.claude/templates/code-review.md` | 代码质量审查 |
| Bug修复 | `.claude/templates/bugfix.md` | Bug 修复任务 |
| 新功能 | `.claude/templates/feature.md` | 功能开发 |
| 重构 | `.claude/templates/refactor.md` | 代码重构 |
| 测试 | `.claude/templates/test.md` | 测试用例生成 |
| 文档 | `.claude/templates/docs.md` | 文档生成 |

### 6.3 工作流命令

```bash
./scripts/dev-workflow.sh lint        # 代码检查
./scripts/dev-workflow.sh format      # 代码格式化
./scripts/dev-workflow.sh typecheck   # 类型检查
./scripts/dev-workflow.sh test        # 运行测试
./scripts/dev-workflow.sh pre-commit  # 完整检查
./scripts/dev-workflow.sh clean       # 清理缓存
```

### 6.4 会话管理

```bash
# 列出所有会话
./scripts/session-manager.sh list

# 恢复会话
./scripts/session-manager.sh resume <会话名>

# 删除会话
./scripts/session-manager.sh delete <会话名>

# 清理所有会话
./scripts/session-manager.sh clear
```

### 6.5 智能模型选择

```bash
# 查看推荐模型
./scripts/model-selector.sh --show

# 自动分析任务类型并推荐
./scripts/model-selector.sh -a "修复登录bug"

# 指定任务类型
./scripts/model-selector.sh -t coding "写一个排序算法"
```

支持的任务类型:
- `reasoning` - 推理分析
- `coding` - 代码开发
- `writing` - 写作创作
- `general` - 通用对话
- `analysis` - 数据分析
- `review` - 代码审查

---

## 7. 故障排除

### 7.1 常见问题

**问题1: Claude Code 无法连接**
```
error: Unable to connect to API (ECONNRESET)
```
**解决方案**: 
1. 使用本地聊天工具: `./run-local-ai.sh chat`
2. 或确保网络/代理设置正确

**问题2: LM Studio 模型未加载**
```
LM Studio: 不可用
```
**解决方案**:
1. 打开 LM Studio 应用
2. 加载至少一个模型
3. 确保 API 服务器运行 (端口 1234)

**问题3: 前端无法访问**
```
curl: (7) Failed to connect
```
**解决方案**:
```bash
cd app && npm run dev
```

**问题4: API Key 无效**
```
API Key 状态: ✗ 未配置
```
**解决方案**:
```bash
./scripts/set-api-key.sh -s "sk-ant-api03-你的密钥"
```

### 7.2 服务状态检查

```bash
# 一键检查所有服务
./run-local-ai.sh status

# 手动检查各服务
curl http://localhost:8001/api/v1/health    # 后端
curl http://localhost:1234/v1/models       # LM Studio
curl http://localhost:11434/api/tags       # Ollama
```

### 7.3 日志位置

| 服务 | 日志位置 |
|------|----------|
| MoRE OS 后端 | 终端输出 |
| 前端 | `/tmp/more-os-frontend.log` |
| 本地代理 | `/tmp/local-llm-server.log` |

---

## 附录

### A. 快捷命令汇总

```bash
# 启动系统
cd more_core && python3 -m more_core.cli serve --port 8001
cd app && npm run dev

# 一键启动菜单
./run-local-ai.sh

# 本地模型聊天
./run-local-ai.sh chat
python3 scripts/lmstudio-chat.py "你的问题"

# Claude Code
./run-local-ai.sh i              # 交互模式
./run-local-ai.sh t "任务"       # 快速任务
./run-local-ai.sh lmstudio        # LM Studio
./run-local-ai.sh ollama          # Ollama

# 工具
./run-local-ai.sh models          # 查看模型
./run-local-ai.sh status          # 状态诊断
```

### B. 环境变量

```bash
# API Key (必需)
export ANTHROPIC_API_KEY="sk-ant-api03-local-proxy-key"

# 可选配置
export ANTHROPIC_API_BASE=http://localhost:8080  # 本地代理
export OPENAI_API_BASE=http://localhost:1234/v1 # LM Studio
```

### C. 文件结构

```
QNMing-MoRE-OS/
├── run-local-ai.sh                    # 一键启动主脚本
├── scripts/
│   ├── claude-local-run.sh            # Claude Code 启动脚本
│   ├── lmstudio-chat.py                # 本地模型聊天工具
│   ├── local-chat.sh                   # 交互式本地聊天
│   ├── model-selector.sh               # 智能模型选择
│   ├── session-manager.sh              # 会话管理
│   ├── dev-workflow.sh                 # 开发工作流
│   ├── set-api-key.sh                  # API Key 管理
│   ├── local-llm-server.py              # 本地 API 代理
│   └── local-proxy.py                  # 简单代理
├── .claude/
│   ├── settings.json                   # Claude Code 设置
│   ├── CLAUDE.md                       # 项目记忆
│   ├── shortcuts.json                   # 快捷命令
│   ├── agents/                         # 自定义子代理
│   ├── templates/                      # 提示词模板
│   └── mcp/                           # MCP 配置
└── more_core/                         # MoRE OS 核心
```

---

**版本**: 1.0  
**更新日期**: 2026-05-10  
**作者**: QNMing MoRE OS Team