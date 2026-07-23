# QNMing MoRE OS v0.8.0 — 代码审计报告

**日期**: 2026-07-07  
**版本**: v0.8.0  
**Python**: 3.14.3 · **Node**: v25.9.0  
**后端正运行**: LM Studio ✓ · Ollama ✓  
**API Server**: 未启动 · **前端**: 未启动

---

## 测试结果摘要

| 测试 | 通过/总数 | 通过率 | 失败明细 |
|------|----------|--------|---------|
| pytest (后端) | **436/438** | **99.5%** | 2 failed |
| vitest (前端) | **22/24** | **91.7%** | 2 failed |
| ruff lint | — | — | **151 errors** (130 auto-fixable) |
| mypy typecheck | — | — | **520 errors** in 79 files |
| tsc | — | — | **9 errors** in 5 files |
| eslint | — | — | **53 problems** (50 errors, 3 warnings) |

---

## 1. 测试失败分析

### 1.1 后端测试失败 (2个)

| 测试 | 原因 |
|------|------|
| `test_reject_dangerous_import` | SandboxValidator 错误消息不匹配：期待 `"Disallowed import"`，实际 `"blocked keyword: os.system"` |
| `test_memory_store_tracks_entries` | 计数断言失败：`assert 2 == 1` — memory store 持久化计数不准确 |

### 1.2 前端测试失败 (2个)

| 测试 | 原因 | 差值 |
|------|------|------|
| `NumberPrecision > formats latency correctly` | `NumberPrecision.latency(150.5)` 返回 `"151ms"` 而非 `"150ms"` | 四舍五入精度问题 |
| `NumberPrecision > formats duration compact` | `durationCompact(150)` 返回 `"0.1K"` 而非 `"0.2K"` | 四舍五入精度问题 |

---

## 2. 代码质量问题

### 2.1 Ruff Lint (151 errors)

主要问题集中在：

- **`runtime/orchestrator.py`**: 24 个未使用的 import（SandboxConfig, ToolRegistry, RequestCache, HandManager 等）
- **测试文件 (20+ 文件)**: 大量未使用的 import（`pytest`, `asyncio`, `AuditRecord` 等）
- **`tests/test_integration_extended.py`**: 40+ 未使用的 import
- **`sandbox/__init__.py`**: 未使用的 `SandboxPolicy`, `default_policy`, `reset_default_policy`
- **`security/__init__.py`**: 未使用的 `TaintContext`
- **`zen_rules.py`**: 未使用的局部变量 `operation`

### 2.2 Mypy Type Check (520 errors)

**最严重的类型问题分类：**

| 类别 | 文件 | 数量 | 影响 |
|------|------|------|------|
| `"MoRECore" has no attribute "X"` | 18 文件 | ~200 | **严重** — 动态属性在 `MoRECore` 上被广泛使用但未声明类型 |
| `Missing type arguments for generic type "dict"` | 30+ 文件 | ~80 | 泛型 `dict` 未指定键值类型 |
| `Returning Any from function declared to return "X"` | 15+ 文件 | ~50 | 返回类型与声明不匹配 |
| `Incompatible return value type` | 10+ 文件 | ~20 | LLM provider 的 `stream()` 返回 `AsyncIterator` 而非 `Coroutine[..., AsyncIterator]` |
| `Function is missing a return type annotation` | 15+ 文件 | ~20 | 缺少返回类型注解 |
| `Module has no attribute "StreamWriterProtocol"` | `mcp/transport.py` | 2 | 使用私有/不存在的 asyncio API |
| `Unused "type: ignore"` | 3 处 | 3 | 不再需要的忽略注释 |

**核心问题**: `MoRECore` 类在运行时通过 `__init__` 动态添加属性（如 `core.llm`, `core.tools`, `core.audit`），但类型注解未更新。这是最根本的类型系统不匹配，影响了几乎所有层和 API 路由器的类型检查。

### 2.3 ESLint (50 errors, 3 warnings)

| 类别 | 位置 | 数量 |
|------|------|------|
| `@typescript-eslint/no-explicit-any` | 8 文件 | 16 errors |
| `react-hooks/set-state-in-effect` | 3 文件 | 3 errors |
| `react-hooks/purity` (Date.now/Math.random in render) | 2 文件 | 5 errors |
| `react-refresh/only-export-components` | 6 shadcn/ui 文件 | 6 errors |
| `@typescript-eslint/no-unused-vars` | 5 文件 | 6 errors |
| `react-hooks/immutability` (useMahjongSocket) | 1 文件 | 1 error |
| `no-unsafe-optional-chaining` | 1 文件 | 1 error |
| `react-hooks/exhaustive-deps` (warning) | 2 文件 | 3 warnings |

---

## 3. 与上一次审计对比 (v0.6.0-alpha → v0.8.0)

| 指标 | 2026-06-05 (v0.6.0) | 2026-07-07 (v0.8.0) | 变化 |
|------|:---:|:---:|:----:|
| 测试总数 | 425 | 438 | ↗ +13 |
| 测试通过 | 414 (97.4%) | 436 (99.5%) | ↗ |
| 测试失败 | 11 (2.6%) | 2 (0.5%) | ↗ **大幅改善** |
| Ruff errors | 未记录 | 151 | — |
| Mypy errors | 未记录 | 520 | — |

**关键改进**: 之前审计报告的 11 个测试异步 API 不匹配问题已全部修复。当前 2 个失败是新的边缘情况。

---

## 4. 环境状态

| 组件 | 状态 |
|------|------|
| Python 3.14.3 | ✅ `.venv` 可用 |
| Node v25.9.0 / npm 11.12.1 | ✅ |
| LM Studio (port 1234) | ✅ **运行中** |
| Ollama (port 11434) | ✅ **运行中** |
| API Server (port 8011) | ❌ 未启动 |
| Frontend Dev (port 3002) | ❌ 未启动 |
| .venv 隔离性 | ✅ 专属于当前项目目录 |

---

## 5. 建议修复优先级

### P0 (Critical)
1. **MoRECore 动态属性类型注解** — 影响所有层和 API 路由器的类型安全性
2. **MCP transport 私有 API** — `StreamWriterProtocol` 在 Python 3.14 中不存在

### P1 (High)
3. **前端四舍五入测试精度** — `format.test.ts` 中 2 个失败的浮点断言
4. **SandboxValidator 错误消息** — 测试字符串不匹配
5. **清理 orchestrator.py 未使用的 import** — 24 个 `F401` 警告

### P2 (Medium)
6. **泛型 `dict` 类型注解** — 跨 30+ 文件的 ~80 处
7. **React hooks purity 问题** — `Date.now()` / `Math.random()` 在渲染中
8. **`any` 类型替换** — 前端 16 处 `no-explicit-any`

---

## 6. 启动说明

要启动系统：

```bash
# 后端 (port 8011)
make serve

# 前端 (port 3003)
cd app && npm run dev

# 验证
make health
```
