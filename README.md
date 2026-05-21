# QNMing MoRE OS

> **Neuro-Symbolic Metacognitive Self-Evolving Agent OS**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)](https://python.org)
[![Version](https://img.shields.io/badge/version-0.3.0-orange.svg)](more_core/more_core/version.py)

---

## 项目简介

**QNMing MoRE OS** 是一款神经符号元认知混合架构的自进化 Agent 操作系统内核，具备六层分层架构（L0–L5），支持从简单任务执行到自主进化的完整能力谱系。

### 核心特性

- **六层架构 (L0–L5)**: 执行 → 编排 → 进化 → 符号推理 → 认知 → 元认知
- **受控自进化**: DGM (达尔文哥德尔机) + HyperAgents，沙箱隔离 + 审计 + 人类 veto
- **神经-符号融合**: NSPA-AI 三层架构 + AOW 本体兼容
- **本地优先**: 支持 Ollama / LMStudio / OpenAI 兼容，内置 fallback 链
- **行业插件**: 领域无关内核 + Industry Pack 扩展机制
- **治理审计**: AuditLogger JSONL 链路，输出 who-did-what-why 审计轨迹

---

## 仓库结构

```text
QNMing-MoRE-OS/
├── more_core/              # Python 核心内核（pip 可安装包）
│   ├── more_core/          #   源码：core/ layers/ llm/ tools/ plugins/ ...
│   ├── tests/              #   测试套件（48/48 通过）
│   ├── examples/           #   示例插件
│   ├── pyproject.toml      #   包配置
│   └── ARCHITECTURE.md     #   架构白皮书
├── app/                    # 前端 Dashboard（React + Vite + shadcn/ui）
│   ├── src/                #   React 源码
│   ├── server/             #   BFF 后端（FastAPI）
│   └── package.json        #   前端依赖
├── plugins/                # 行业插件目录
│   └── mahjong-industry-pack/  # 麻将策略 — 插件个案
├── docs/                   # 文档与报告
│   ├── reports/            #   战略/分析/可行性报告
│   └── images/             #   架构图/对比图
├── scripts/                # 工具脚本
│   └── setup_env.sh        #   环境检测与一键安装
├── Makefile                # 开发快捷命令
├── LICENSE                 # Apache-2.0
├── CONTRIBUTING.md         # 贡献指南
└── CHANGELOG.md            # 版本变更记录
```

---

## 快速开始

### 前置条件

- Python 3.10+
- Node.js 18+（仅前端 Dashboard 需要）
- Git

### 一键安装

```bash
# 克隆仓库
git clone https://github.com/QNMing/QNMing-MoRE-OS.git
cd QNMing-MoRE-OS

# 安装核心包（含 API server）
make install

# 或手动：
cd more_core && pip install -e ".[all]"
```

### 启动服务

```bash
# 方式一：Makefile
make serve

# 方式二：CLI
more-os serve --host 0.0.0.0 --port 8001

# 方式三：Python API
python3 -c "
import asyncio
from more_core import MoRECore, TaskRequest, TaskType

async def main():
    core = MoRECore.from_env()
    await core.start()
    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query='Hello MoRE'))
    print(result.output)
    await core.stop()

asyncio.run(main())
"
```

### 运行测试

```bash
make test
# 或: cd more_core && python3 -m pytest tests/ -v
```

---

## 持久化配置（可选）

默认为内存模式。设置环境变量即可启用 SQLite 持久化：

```bash
export MORE_MEMORY_DB=data/memory.db
export MORE_EVOLUTION_DB=data/evolution.db
```

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

---

## 许可证

[Apache License 2.0](LICENSE)

---

## 贡献

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解贡献流程。

---

**QNMing MoRE Team** · 2026
