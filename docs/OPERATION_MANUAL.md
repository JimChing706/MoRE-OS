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
| MoRE OS API | 8011 | 后端 API 服务 |
| Dashboard | 3003 | 前端 Web 界面 |
| LM Studio | 1234 | 本地模型 API |
| Ollama | 11434 | 本地模型 API |

---

## 2. 快速启动

### 2.1 一键安装

```bash
bash install.sh --install
```

### 2.2 启动服务

```bash
make start                    # 后台启动 API → http://localhost:8011
cd app && npm run dev         # 前端 Dashboard → http://localhost:3003 (另一个终端)
```

### 2.3 健康检查

```bash
bash scripts/health_check.sh   # 全栈验证
make health                    # API 速查
```

### 2.4 使用启动菜单

```bash
./run-local-ai.sh              # 交互式菜单
./run-local-ai.sh start        # 直接启动
./run-local-ai.sh status       # 查看状态
./run-local-ai.sh health       # 健康检查
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

## 4. LLM 集成

MoRE OS 通过 `more_core/.env` 配置 LLM Provider，支持自动 fallback 链。

### 4.1 配置 Provider

```bash
cp more_core/.env.template more_core/.env
# 编辑 more_core/.env
```

### 4.2 支持的 Provider

| Provider | 端口 | 类型 | 说明 |
|----------|------|------|------|
| LM Studio | 1234 | 本地 | 大模型推理 (primary) |
| Ollama | 11434 | 本地 | 轻量推理 (fallback) |
| DeepSeek | cloud | 远程 | 可选云 API |
| OpenAI 兼容 | 自定义 | 远程 | 支持 20+ Provider |

### 4.3 测试 LLM 连接

```bash
curl http://localhost:1234/v1/models   # LM Studio
curl http://localhost:11434/api/tags   # Ollama
```

---

## 5. 一键启动方案

### 5.1 主脚本功能

`run-local-ai.sh` 提供以下功能:

| 功能 | 菜单选项 | 快捷命令 |
|------|----------|----------|
| 启动 API | [1] | `./run-local-ai.sh start` |
| 停止 API | [2] | `./run-local-ai.sh stop` |
| 重启 API | [3] | `./run-local-ai.sh restart` |
| 健康检查 | [4] | `./run-local-ai.sh health` |
| 本地聊天 | [5] | `./run-local-ai.sh chat` |
| 查看模型 | [6] | `./run-local-ai.sh models` |
| 查看日志 | [7] | `./run-local-ai.sh logs` |

### 5.2 核心脚本说明

| 脚本 | 功能 |
|------|------|
| `run-local-ai.sh` | 主入口，服务启动菜单 |
| `install.sh` | 一键安装脚本 |
| `scripts/health_check.sh` | 全栈健康验证 |
| `scripts/lmstudio-chat.py` | 本地模型聊天工具 |
| `scripts/model-selector.sh` | 智能模型选择 |
| `scripts/session-manager.sh` | 会话管理 |
| `scripts/dev-workflow.sh` | 开发工作流 |
| `scripts/setup_env.sh` | 旧版环境检查 (已弃用) |

### 5.3 使用示例

**场景1: 全栈启动**
```bash
make start && cd app && npm run dev
```

**场景2: 本地模型聊天**
```bash
./run-local-ai.sh chat
```

**场景3: 健康检查**
```bash
bash scripts/health_check.sh
```

**场景4: 查看所有可用模型**
```bash
./run-local-ai.sh models
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

### 6.6 可观测性与运行指标

MoRE OS 内置零依赖实时看板与 Prometheus 导出，覆盖五类核心指标：

| 指标族 | 端点 | 说明 |
|--------|------|------|
| **运行健康总览** | `GET /api/v1/metrics/overview` | 五类指标汇总 + 统一裁决（healthy/degraded/critical）+ 合并告警 |
| LLM 调用 | `GET /api/v1/metrics/llm` | token 消耗、延迟 p50/p95、成功率（按 provider/model） |
| 交付成功率 | `GET /api/v1/delivery/stats` | 交付/拦截/失败、闸门通过率 |
| 治理拦截率 | `GET /api/v1/metrics/governance` | blocked_requests/requests + 命中规则 + 阈值告警 |
| Council 复评 | `GET /api/v1/metrics/council` | 下修率、共识分布、平均调整量 |
| Provider 健康 | `GET /api/v1/metrics/providers` | 健康 / 无效模型 / 推理探针 + 告警 |
| Prometheus | `GET /api/v1/metrics/governance/prometheus` | `more_os_*` 文本导出 |

**看板**：浏览器打开 `http://localhost:8011/api/v1/metrics/dashboard`，
页面内输入 `MORE_API_KEY`（仅存本机 localStorage），每 5 秒自动刷新。

**鉴权**：除看板页面本身外，所有指标端点都需要 `Authorization: Bearer <MORE_API_KEY>`。

```bash
KEY=$(grep -E '^MORE_API_KEY=' more_core/.env | cut -d= -f2-)
curl -H "Authorization: Bearer $KEY" http://localhost:8011/api/v1/metrics/overview
```

**告警语义**：`overall` 由合并告警的最高级别决定。

| 级别 | 含义 | 典型 code |
|------|------|-----------|
| critical | 已确证会失败或被绕过 | `state_invalid_model`、`provider_inference_failed`、`provider_unhealthy`、`provider_invalid_model` |
| warning | 降级 / 需关注 | `fallback_chain_degraded`、`governance_blocked_rate`、`destructive_request_blocks`、`provider_preflight_missing` |

**LLM 深度体检**（发一次真实最小补全，验证"能否真正出 token"，而非仅 `/models` 可达）：

```bash
curl -H "Authorization: Bearer $KEY" "http://localhost:8011/api/v1/llm/preflight?probe=1"
```

> 常见陷阱：`provider.health()` 只探 `/models`，LM Studio 在**推理时**才可能返回
> HTTP 500。若"看起来健康但任务失败"，请用上面的 `probe=1` 复核。

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
curl http://localhost:8011/api/v1/health    # API
curl http://localhost:1234/v1/models       # LM Studio
curl http://localhost:11434/api/tags       # Ollama

# 运行健康总览（需 API Key，见 6.6）
KEY=$(grep -E '^MORE_API_KEY=' more_core/.env | cut -d= -f2-)
curl -H "Authorization: Bearer $KEY" http://localhost:8011/api/v1/metrics/overview
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
make start                    # API → http://localhost:8011
cd app && npm run dev         # Dashboard → http://localhost:3003

# 一键启动菜单
./run-local-ai.sh

# 快捷命令
./run-local-ai.sh start        # 启动 API
./run-local-ai.sh stop         # 停止 API
./run-local-ai.sh restart      # 重启 API
./run-local-ai.sh status       # 服务状态
./run-local-ai.sh health       # 健康检查
./run-local-ai.sh chat         # 本地 LLM 聊天
./run-local-ai.sh models       # 查看模型
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
├── install.sh                         # 一键安装脚本
├── run-local-ai.sh                    # 服务启动菜单
├── Makefile                           # 开发/运维命令
├── more_core/                         # MoRE OS Python 核心
│   ├── .env.template                  #   环境变量模板
│   ├── .env                           #   当前环境配置
│   └── more_core/                     #   源码
├── app/                               # 前端 Dashboard
├── plugins/                           # 行业插件
├── scripts/
│   ├── health_check.sh                #   全栈健康验证
│   ├── lmstudio-chat.py               #   本地模型聊天
│   ├── model-selector.sh              #   模型选择
│   ├── session-manager.sh             #   会话管理
│   ├── dev-workflow.sh                #   开发工作流
│   └── setup_env.sh                   #   旧版环境检查 (已弃用)
├── docs/
│   ├── INSTALL.md                     #   安装指南
│   └── OPERATION_MANUAL.md            #   本文件
├── data/                              # 运行时数据库
└── README.md                          # 项目说明
```

---

**版本**: 1.0  
**更新日期**: 2026-05-10  
**作者**: QNMing MoRE OS Team