# QNMing MoRE OS — Agent OS Kernel

> **定位**：QNMing MoRE OS v3.0 平台化工程的内核层（开源 Apache‑2.0）。对应《MoRE 平台化竞品比选可行性研究报告》§8.2 的 **Layer 1 — MoRE Core**。
>
> 本包从 MVP（含麻将等娱乐性示例）中抽离**平台级、领域无关**的核心抽象：L0–L5 分层、服务注册、事件总线、插件、LLM 多 Provider、沙箱、路由、本体、进化、元认知、治理。
>
> 任何行业场景（代码助手 / 数据分析 / 客服 / 教育 / 量化 / 棋牌等）都以 **插件 (Industry Pack)** 的形式接入，内核不做任何领域耦合。

---

## 设计原则（与既有报告对齐）

1. **领域无关内核 + 行业插件壳**：Core 不包含任何棋牌/麻将/特定游戏代码；`examples/` 仅演示通用技能（代码助手）。
2. **分层可替换**：每一 Layer 都是 `Protocol` 接口 + 基线实现，可被插件整体替换（G2）。
3. **本地优先、Provider 中立**：LLM Manager 支持 Ollama / LMStudio / OpenAI 兼容，内置 fallback 链（G3）。
4. **受控自进化**：L2 DGM、L5 HyperAgents 默认**关闭**，开启需显式配置 + 沙箱 + 审计（G4）。
5. **本体治理与审计**：基于 AOW v1.0 的八类实体映射输出审计链路（G5）。
6. **插件接口稳定性**：Plugin 协议向下兼容至少 12 个月（G6）。

> 设计目标 G1–G6 详见根目录 `MoRE_Platformization_Competitive_Feasibility_Report.md` §1。

---

## 目录结构

```text
more_core/
├── core/              # 类型、错误、配置、服务注册、事件总线
├── tools/             # ToolRegistry + 内置工具（python_exec / shell_exec / memory_*）
├── plugins/           # 插件接口、管理器、Plugin SDK + scaffold 脚手架
├── llm/               # LLM Manager + Ollama/LMStudio/OpenAI 兼容 Provider
├── sandbox/           # SubprocessSandbox + LinuxSandbox (cgroup v2 硬化) + 平台工厂
├── layers/            # L0–L5 Layer 接口与基线实现
├── router/            # 难度感知层路由器（OMAC 思路）
├── memory/            # episodic / semantic / procedural 三路记忆 + SQLite 持久化
├── ontology/          # AOW 实体 + 本体引擎 + 前向链 RuleEngine
├── evolution/         # DGM 进化引擎 + BenchmarkRunner 评估回路 + SQLite 归档
├── metacognition/     # 校准器 + HyperAgent 自修改（受控）
├── governance/        # 审计日志 + 合规约束
├── runtime/           # MoRECore 运行时（装配所有子系统）
├── api/               # FastAPI 平台接口（可选）
└── cli.py             # 命令行入口
```

## 快速开始

```bash
pip install -e ".[api]"
more-os serve --host 0.0.0.0 --port 8001
```

Python API：

```python
from more_core import MoRECore, TaskRequest, TaskType

core = MoRECore.from_env()         # 从环境变量装配
await core.start()
result = await core.execute(TaskRequest(
    type=TaskType.CODE_GENERATION,
    query="写一个快速排序",
))
print(result.output)
```

### 持久化（可选）

默认为内存模式。设置环境变量即可启用 SQLite 持久化：

```bash
export MORE_MEMORY_DB=data/memory.db
export MORE_EVOLUTION_DB=data/evolution.db
```

### 自定义工具

```python
from more_core.tools import ToolRegistry, ToolDefinition, ToolResult

async def my_handler(params):
    return ToolResult(tool="my_tool", success=True, output=params["input"].upper())

core.tools.register(ToolDefinition(
    name="my_tool",
    description="Uppercase the input",
    parameters_schema={"type": "object", "properties": {"input": {"type": "string"}}},
    handler=my_handler,
))
```

### 创建插件 (Industry Pack)

```python
from more_core.plugins.sdk import scaffold_plugin

scaffold_plugin("./plugins", "my-industry-pack", description="A custom plugin")
```

生成标准目录：`plugin.json` + `main.py` + `README.md`，即可发布为独立 Python 包。

## 与 MVP (`app/`) 的关系

- `app/` 是前端演示 + 早期 MVP，含娱乐性脚本（已清理 `automate_mahjong_development.py`）。
- `more_core/` 是**平台内核**，不依赖 `app/`。未来 `app/` 的后端 (`server/`) 将迁移为 `more_core.api` 的一个部署形态。

## 测试

```bash
pip install -e ".[dev]"
python3 -m pytest tests/ -v
```

当前覆盖：工具注册、规则引擎、DGM 评估回路、SQLite 持久化、Plugin SDK、路由（含可扩展性）、沙箱、事件总线、治理策略、运行时集成、L0 执行层、API 端点、LLM fallback、CJK/Unicode 合规、全修复项回归（233/233 通过）。

## 详细文档

- **[USER_MANUAL.md](USER_MANUAL.md)** — 完整用户手册：配置、SDK、REST API、插件开发、运维与故障排查
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — 架构白皮书
- **[AUDIT_REPORT.md](AUDIT_REPORT.md)** — 安全审计报告与修复记录

## 许可

Apache‑2.0
