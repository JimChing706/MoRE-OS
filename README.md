# QNMing MoRE OS

> **Neuro-Symbolic Metacognitive Self-Evolving Agent OS**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)](https://python.org)
[![Version](https://img.shields.io/badge/version-0.5.0-orange.svg)](more_core/more_core/version.py)

---

## 项目简介

**QNMing MoRE OS** 是一款神经符号元认知混合架构的自进化 Agent 操作系统内核，具备六层分层架构（L0–L5），支持从简单任务执行到自主进化的完整能力谱系。

### 核心特性

- **六层架构 (L0–L5)**: 执行 → 编排 → 进化 → 符号推理 → 认知 → 元认知
- **受控自进化**: DGM (达尔文哥德尔机) + HyperAgents，沙箱隔离 + 审计 + 人类 veto
- **神经-符号融合**: NSPA-AI 三层架构 + AOW 本体兼容
- **本地优先**: 支持 Ollama / LMStudio / OpenAI / DeepSeek 等 20+ Provider，内置 fallback 链
- **流式输出**: SSE (Server-Sent Events) 端点，token 级实时推送
- **A2A 协议**: Agent-to-Agent 任务委托，可被 Codex CLI / Claude Code 编排
- **MCP 双向**: Client（连接外部 MCP Server）+ Server（暴露 29 个工具给外部 Agent）
- **行业插件**: 领域无关内核 + Industry Pack 扩展机制（麻将、扫雷已集成）
- **治理审计**: RBAC + Taint Tracking + AuditLogger JSONL + PolicyEnforcer，16 层安全防护
- **CJK 原生**: 中日韩多语言感知、语义长度计算、本地化系统提示

---

## 仓库结构

```text
QNMing-MoRE-OS/
├── more_core/              # Python 核心内核（pip 可安装包）
│   ├── more_core/          #   源码：core/ layers/ llm/ tools/ plugins/ mcp/ a2a/
│   ├── tests/              #   测试套件
│   ├── examples/           #   示例插件
│   ├── pyproject.toml      #   包配置
│   ├── .env                #   环境配置模板
│   └── ARCHITECTURE.md     #   架构白皮书
├── app/                    # 前端 Dashboard（React + Vite + shadcn/ui）
│   ├── src/                #   React 源码
│   ├── server/             #   BFF 后端（FastAPI）
│   └── package.json        #   前端依赖
├── plugins/                # 行业插件目录
│   ├── mahjong-industry-pack/  # 麻将策略
│   ├── minesweeper_game/       # 扫雷游戏引擎
│   └── minesweeper_agent/      # 扫雷 AI Agent
├── docs/                   # 文档与报告
├── scripts/                # 工具脚本
├── Makefile                # 开发快捷命令
├── LICENSE                 # Apache-2.0
└── CHANGELOG.md            # 版本变更记录
```

---

## 快速开始

### 前置条件

- Python 3.10+
- Node.js 18+（仅前端 Dashboard 需要）
- Ollama 或 LM Studio（可选，用于真实 LLM）

### 一键安装

```bash
git clone https://github.com/QNMing/QNMing-MoRE-OS.git
cd QNMing-MoRE-OS

# 创建虚拟环境并安装
python3 -m venv .venv
source .venv/bin/activate
cd more_core && pip install -e ".[api]"
```

### 配置 LLM

编辑 `more_core/.env`：

```bash
# Ollama（推荐，本地免费）
MORE_OLLAMA_ENDPOINT=http://localhost:11434
MORE_OLLAMA_MODEL=qwen2.5:7b

# LM Studio（大模型推理）
MORE_LMSTUDIO_ENDPOINT=http://localhost:1234/v1
MORE_LMSTUDIO_MODEL=qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled

# Provider 优先级
MORE_LLM_FALLBACK_CHAIN=ollama,lmstudio
```

### 启动服务

```bash
# API 服务
make serve
# 或: .venv/bin/python3 -m more_core.cli serve --port 8001

# 前端 Dashboard
cd app && npm install && npm run dev
```

### MCP Server 模式（供 Codex/Claude 调用）

```bash
# stdio 模式 — 供外部 Agent 通过 MCP 协议编排
.venv/bin/python3 -m more_core.cli mcp-serve
```

### 运行测试

```bash
make test
```

---

## API 端点速览

| 类别 | 端点 | 说明 |
|------|------|------|
| 健康 | `GET /api/v1/health` | 系统健康 + Provider 状态 |
| 任务 | `POST /api/v1/tasks/execute` | 执行任务（全量返回） |
| 流式 | `POST /api/v1/tasks/stream` | SSE token 流式输出 |
| LLM | `GET /api/v1/llm/providers` | 可用 Provider 信息 |
| Hands | `GET /api/v1/hands` | 注册的自主 Hands |
| MCP | `GET /api/v1/mcp/servers` | 已连接的 MCP Server |
| A2A | `POST /a2a` | Agent-to-Agent 任务委托 |
| A2A | `GET /a2a/agent-card` | Agent 能力卡片 |

完整 API 文档：`http://localhost:8001/api/docs`

---

## 设计原则

| 编号 | 原则 | 说明 |
|------|------|------|
| G1 | 领域无关内核 + 行业插件壳 | Core 零领域耦合，行业扩展通过 Industry Pack |
| G2 | 分层可替换 | 每层都是 Protocol + 基线实现，可被插件整体替换 |
| G3 | 本地优先、Provider 中立 | 支持多 LLM Provider + fallback 链 |
| G4 | 受控自进化 | L2/L5 默认关闭，开启需显式配置 + 沙箱 + 审计 |
| G5 | 本体治理与审计 | 兼容 AOW v1.0 八类实体，输出审计链路 |
| G6 | 插件接口稳定性 | Plugin 协议向下兼容至少 12 个月 |

## 竞品定位

MoRE OS 是 **"带治理的企业级 Agent OS"** —— 在编码Agent（Codex/Claude）和轻量框架（OpenClaw/LangGraph）之间占据安全治理层：

| 维度 | MoRE OS | Codex CLI | Claude Code | OpenFang |
|------|:---:|:---:|:---:|:---:|
| 安全层数 | 16 ★★★★★ | 多层 ★★★★☆ | Basic ★★★☆☆ | 16 ★★★★★ |
| CJK 支持 | ★★★★★ | ★★☆☆☆ | ★★☆☆☆ | ★★☆☆☆ |
| MCP Server | ✅ | ✅ | ❌ | ✅ |
| A2A 协议 | ✅ | Symphony | Dispatch | Agent工厂 |
| 符号推理 | L3 引擎 | ❌ | ❌ | ❌ |
| 元认知 | Calibrator | ❌ | ❌ | ❌ |
| 本地免费 | ✅ | $20/月 | $20/月 | ✅ |

详见 `docs/reports/` 中的竞品对比报告。

---

## 许可证

[Apache License 2.0](LICENSE)

## 贡献

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

**QNMing MoRE Team** · 2026
