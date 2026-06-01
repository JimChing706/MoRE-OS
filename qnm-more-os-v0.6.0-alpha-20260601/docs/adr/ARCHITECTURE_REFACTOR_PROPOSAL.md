# MoRE OS 架构重构方案 — ADR-001

**日期**: 2026-05-27  
**状态**: 提案  
**影响范围**: `security/`, `governance/`, `sandbox/`, `llm/`, `runtime/orchestrator.py`, `layers/l0_execution.py`

---

## 概述

当前代码库存在三大架构隐患：
1. 两个不兼容的 RBAC 系统均未接入实际执行点
2. 三种沙箱实现接口不统一，`SecureSandbox` 沦为死代码
3. 11 种任务类型的模型路由映射到同一模型，抽象完全死亡

---

## 1. RBAC 重构方案

### 1.1 当前状态

| 维度 | `security/rbac.py` | `governance/rbac.py` |
|------|--------------------|----------------------|
| 入口类 | `RBACManager` | `RBACPolicy` |
| 权限分隔符 | 点号 (`task.execute`) | 冒号 (`task:execute`) |
| 角色模型 | `Role` dataclass + user-role mapping | `Role` Enum + `User` dataclass |
| 最终用户 | 未接入任何执行点 | 未实例化，未导出 |
| 启用方式 | `enable()` / `disable()` 开关 | 无开关，始终生效 |
| 错误处理 | 返回 `bool` | 抛出 `PermissionError` |
| 持久化 | 纯内存 | 纯内存 |

### 1.2 根本问题

两个系统的核心差异在**权限模型语义**上：
- `security/` 的 `Permission` 枚举覆盖了工具级粒度（`TOOL_SHELL`, `TOOL_FILE_WRITE`）
- `governance/` 的 `Permission` 枚举覆盖了资源级粒度（`MEMORY_READ`, `EVOLUTION_WRITE`）
- 两者互补但不兼容

在 `orchestrator.py` 中，`self.rbac = RBACManager()` 已被实例化，但 `rbac.enabled` 仅出现在 `monitor.py` 的 health 返回中作为字段显示，从未实际用于拦截。

### 1.3 设计方案：统一 RBAC 层

```
┌─────────────────────────────────────────────────────┐
│  RBACMiddleware (统一入口)                          │
│  - 接收 FastAPI Depends / 工具调用钩子              │
│  - 查找用户 → 聚合所有角色的权限 → bool/raise       │
│  - 内存模式 + 可选 SQLite 持久化                    │
├─────────────────────────────────────────────────────┤
│  权限注册表 (PermissionRegistry)                    │
│  - 插件可注册新权限: `rbac.register_perm("game.play")` │
│  - 权限继承: `"tool.*"` 匹配所有 tool 权限          │
├─────────────────────────────────────────────────────┤
│  执行点                                              │
│  - FastAPI Depends: `require_permission("task.execute")` │
│  - 工具调用: `rbac.check(user, "tool.shell")`       │
│  - L0 执行层: `rbac.check(user, "sandbox.execute")`  │
└─────────────────────────────────────────────────────┘
```

#### 统一后的 Permission 枚举

```python
class Permission(str, Enum):
    # 使用冒号命名空间（兼容现有两套命名）
    # task 域
    TASK_EXECUTE = "task:execute"
    TASK_VIEW    = "task:view"
    TASK_DELETE  = "task:delete"
    # hand 域
    HAND_ACTIVATE   = "hand:activate"
    HAND_DEACTIVATE = "hand:deactivate"
    HAND_RUN        = "hand:run"
    HAND_VIEW       = "hand:view"
    # llm 域
    LLM_UPDATE   = "llm:update"
    LLM_VIEW     = "llm:view"
    LLM_VIEW_KEYS = "llm:view_keys"
    # tool 域 (从 security/ 继承)
    TOOL_SHELL     = "tool:shell"
    TOOL_FILE_WRITE = "tool:file_write"
    TOOL_FILE_READ  = "tool:file_read"
    TOOL_PYTHON    = "tool:python"
    # memory 域 (从 governance/ 继承)
    MEMORY_READ   = "memory:read"
    MEMORY_WRITE  = "memory:write"
    MEMORY_DELETE = "memory:delete"
    # evolution 域 (从 governance/ 继承)
    EVOLUTION_READ   = "evolution:read"
    EVOLUTION_WRITE  = "evolution:write"
    EVOLUTION_EXECUTE = "evolution:execute"
    # governance 域
    GOV_RESOLVE = "gov:resolve"
    GOV_VIEW    = "gov:view"
    # system 域
    SYS_CONFIG = "sys:config"
    SYS_ADMIN  = "sys:admin"
    SYS_AUDIT  = "sys:audit"
    # channel 域
    CHANNEL_MANAGE = "channel:manage"
    CHANNEL_VIEW   = "channel:view"
```

#### 执行点接入计划

| 位置 | 接入方式 | 描述 |
|------|----------|------|
| `api/server.py` | `require_permission("sys:admin")` | 管理员端点 |
| `api/routers/tasks.py` | `require_permission("task:execute")` | 任务执行 |
| `api/routers/llm.py` | `require_permission("llm:update")` | LLM 配置修改 |
| `tools/registry.py` | `rbac.check(user_id, perm)` | 工具调用前检查 |
| `layers/l0_execution.py` | `rbac.check(user_id, "tool:shell")` | 沙箱执行前 |
| `hands/manager.py` | `require_permission("hand:activate")` | Hand 激活 |

#### 关键设计决策

1. **不在 `orchestrator.py` 内嵌 RBAC**：`orchestrator` 是编排器，不是安全网关。RBAC 执行点在各模块入口。
2. **FastAPI 层使用 Depends**：`dependencies=[Depends(require_permission("task:execute"))]`，与现有 `_require_api_key` 模式一致。
3. **工具层使用装饰器**：`@requires_permission("tool:shell")` 包装 tool handler。
4. **插件权限自注册**：插件可通过 `rbac.register_permission("game:play", "Play mahjong game")` 扩展权限域。
5. **默认策略**：无 `enable/disable` 开关。不设置 `MORE_ADMIN_USERS` 时允许所有人，设置后非白名单拒绝。

### 1.4 迁移路径

```
Step 1: 在 security/ 下创建 UnifiedRBAC，合并两个 Permission 枚举
Step 2: 删除 governance/rbac.py（功能已合并），更新 governance/__init__.py
Step 3: 在 security/__init__.py 暴露新接口，保留旧 RBACManager 别名（向后兼容）
Step 4: 接入第一个执行点（tools/registry.py），端到端验证
Step 5: 逐步接入剩余执行点
Step 6: 移除旧 RBACManager（标记废弃后一个版本删除）
```

---

## 2. 沙箱统一方案

### 2.1 当前状态

```
                    ┌──────────────────────┐
                    │   create_sandbox()   │ ← 工厂函数，推荐入口
                    │   (linux_sandbox.py) │
                    └──────────┬───────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                   ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
   │Subprocess    │  │LinuxSandbox  │  │  SecureSandbox   │
   │Sandbox       │  │(extends Sub.)│  │ (完全不同的接口)  │
   │              │  │              │  │                   │
   │SandboxResult │  │SandboxResult │  │ dict[str, Any]    │
   │run()         │  │run()         │  │ execute()         │
   │run_python()  │  │(no run_python)│ │ check_command()   │
   └──────────────┘  └──────────────┘  └───────────────────┘
                                                ↑
                                        死代码 ── 未导出、未使用
```

### 2.2 根本问题

1. **接口不统一**：`SubprocessSandbox.run()` 返回 `SandboxResult`，`SecureSandbox.execute()` 返回 `dict[str, Any]`
2. **功能重复**：三份代码都实现了「超时控制 + 子进程管理」，但参数签名不同
3. **能力缺失**：`SubprocessSandbox` 没有命令白名单、没有审计日志；`SecureSandbox` 有这些能力但无法使用
4. **隔离漏洞**：`SubprocessSandbox.run_python()` 直接传 `sys.executable`，子进程继承宿主机的网络和文件系统

### 2.3 设计方案：分层沙箱栈

```
Layer 3: SecureSandbox ── 安全策略层
         - 命令白名单/黑名单
         - 审计日志
         - 进程数限制
         - 输出大小限制
         ↓ 委托
Layer 2: LinuxSandbox ── 内核隔离层 (Linux only)
         - cgroup v2 资源限制
         - unshare PID/网络/挂载命名空间
         - 透明降级到 Layer 1
         ↓ 委托
Layer 1: SubprocessSandbox ── 进程执行层
         - asyncio 子进程管理
         - 超时控制
         - stdin/stdout/stderr 捕获
         ↓ 未修改
Layer 0: OS 进程

统一返回类型: SandboxResult (所有层)
统一工厂: create_sandbox(config: SandboxConfig) → Sandbox
```

#### `SandboxConfig` 统一配置

```python
@dataclass
class SandboxConfig:
    timeout_s: int = 20
    memory_mb: int = 512
    max_output_size: int = 1_048_576  # 1MB
    max_processes: int = 4
    allow_network: bool = False
    allow_filesystem: bool = True
    allowed_paths: list[str] = field(default_factory=lambda: ["/tmp"])
    blocked_commands: list[str] = field(default_factory=lambda: [
        "rm", "dd", "mkfs", "shutdown", "reboot", "kill", "pkill", "sudo"
    ])
    security_level: SecurityLevel = SecurityLevel.BASIC
    audit_enabled: bool = True
    audit_max_entries: int = 1000
```

#### 新接口设计

```python
class Sandbox(Protocol):
    async def run(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> SandboxResult: ...

    async def run_python(self, code: str) -> SandboxResult: ...

    def get_stats(self) -> dict[str, Any]: ...

    def get_audit_log(self, limit: int = 100) -> list[dict]: ...
```

#### 关键设计决策

1. **`SecureSandbox` 作为装饰层**：不重新实现子进程管理，而是包装 `SubprocessSandbox`/`LinuxSandbox`，在其前后插入安全检查
2. **`run_python()` 统一入口**：不再 `subprocess.run([sys.executable, ...])`，而是走完整沙箱栈
3. **审计日志内建**：`SecureSandbox` 的审计能力提升为标准沙箱能力，默认开启
4. **配置驱动选择**：`create_sandbox()` 根据 `SandboxConfig.security_level` 自动组合各层

### 2.4 迁移路径

```
Step 1: 将 SecureSandbox 的审计、命令检查逻辑合并到统一 SandboxConfig
Step 2: SecureSandbox 改为包装 SubprocessSandbox（装饰器模式），统一返回类型
Step 3: 将 SecureSandbox 导出到 sandbox/__init__.py
Step 4: 更新 orchestrator.py 使用新统一沙箱接口
Step 5: 将 tools/builtins.py 中 run_python 调用改为新接口
Step 6: 删除旧的 SecureSandbox（纯代码），移除死的 _posix_limits
```

---

## 3. Task Routing 重构方案

### 3.1 当前状态

```python
# task_router.py 中，所有 11 种任务类型映射到同一模型
TASK_MODEL_MAP: dict[TaskType, ModelBinding] = {
    TaskType.CODE_GENERATION:     ModelBinding("ollama", "qwen2.5:7b"),
    TaskType.MATH_REASONING:      ModelBinding("ollama", "qwen2.5:7b"),
    TaskType.ARCHITECTURE_DESIGN: ModelBinding("ollama", "qwen2.5:7b"),
    TaskType.NLP_TASK:            ModelBinding("ollama", "qwen2.5:7b"),
    # ... 全部相同
}

# 两条 fallback chain 完全相同
FALLBACK_CHAINS = {
    "lmstudio_primary":   [ollama, lmstudio],   # 与 reasoning 完全一样
    "lmstudio_reasoning": [ollama, lmstudio],   # 与 primary 完全一样
}
```

### 3.2 根本问题

1. **抽象不等于复用**：`TASK_MODEL_MAP` 提供了「看起来可配置」的抽象，但实际没有差异化
2. **`DEFAULT_LM_MODEL` 被定义但从未作为 main binding 使用**：它只出现在 fallback chain 里
3. **`set_binding()` 无人调用**：运行时修改绑定能力的 API 存在但无消费方
4. **`ReasoningRouter` 在 `reasoning.py` 独立实现但从未接入 `LLMManager`**
5. **`ModelAliasRegistry` 能解析别名但从未在生成流程中应用**

### 3.3 设计方案：动态模型路由

```
                     ┌──────────────────────────────┐
                     │    DynamicModelRouter          │
                     │                                │
                     │  1. 查询配置的动态映射表         │
                     │  2. 选 provider: 健康检查 + 负载 │
                     │  3. 选模型: 任务类型 + 别名解析  │
                     │  4. 构建 fallback chain          │
                     └──────────┬───────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
   │  配置层       │   │  健康层      │   │  Fallback 层      │
   │  env-driven   │   │  provider    │   │  多级降级         │
   │  任务→模型映射 │   │  health check│   │  熔断恢复         │
   │  别名解析     │   │  延迟检测    │   │  超时隔离         │
   └──────────────┘   └──────────────┘   └──────────────────┘
```

#### 配置驱动设计

```python
# 默认配置（通过 env 覆盖）
MORE_MODEL_ROUTING = {
    "default": {"provider": "ollama", "model": "qwen2.5:7b"},
    "code":    {"provider": "ollama", "model": "qwen2.5-coder:7b"},
    "math":    {"provider": "ollama", "model": "qwen2.5-math:7b"},
    "reasoning": {
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "fallback": [{"provider": "lmstudio", "model": "qwen3.6-35b"}],
    },
}
```

#### 新接口

```python
class DynamicModelRouter:
    def resolve(self, task_type: TaskType) -> ProviderModelPair:
        """返回 (provider, model) 的最佳匹配"""

    def fallback_chain(self, task_type: TaskType) -> list[ProviderModelPair]:
        """返回按优先级排列的降级链"""

    def set_route(self, task_type: TaskType, provider: str, model: str) -> None:
        """运行时修改路由规则"""

    def health(self) -> dict[str, bool]:
        """检查所有注册 provider 的健康状态"""

    def reset_failures(self, provider: str | None = None) -> None:
        """重置熔断计数"""
```

#### 关键设计决策

1. **去除静态 `TASK_MODEL_MAP`**：改为从配置/env 动态加载
2. **集成 `ReasoningRouter`**：将 `reasoning.py` 的 budget_tokens 逻辑合并到路由选择中
3. **集成 `ModelAliasRegistry`**：路由解析时自动应用别名映射
4. **熔断状态持久化**：`_failure_counts` 可选的 SQLite 持久化，重启不丢失
5. **API 端点暴露路由配置**：`GET /api/v1/llm/routing` 实时查看 + `POST` 修改

### 3.4 迁移路径

```
Step 1: 在 task_router.py 中新增 DynamicModelRouter 类
Step 2: 旧 TaskModelRouter 标记为 @deprecated 并委托给 DynamicModelRouter
Step 3: 将配置从 Python 常量改为 env 驱动（MORE_MODEL_ROUTING JSON）
Step 4: 接入 ReasoningRouter + ModelAliasRegistry
Step 5: 更新 l0_execution.py 的调用链
Step 6: 暴露配置 API 端点
Step 7: 移除旧 TaskModelRouter（标记废弃后一个版本删除）
```

---

## 4. 工程化与性能评估

### 4.1 RBAC 性能影响

| 操作 | 当前 | 改造后 | 差异 |
|------|------|--------|------|
| 权限检查 | N/A（未启用） | `O(num_roles)` lookup | 可忽略 |
| 用户查询 | N/A | `O(1)` dict lookup | 可忽略 |
| 权限注册 | N/A | `O(1)` dict insert | 仅初始化时 |
| **端到端延迟** | 0 | ~5μs | 一个 Python dict lookup |

### 4.2 沙箱性能影响

| 操作 | 当前 | 改造后 | 差异 |
|------|------|--------|------|
| 基础执行 | 直接子进程 | 子进程 + 安全检查 | +~50μs |
| 安全检查 | 无 | 命令白名单检查 | O(1)~O(n) |
| 审计日志 | 无 | 追加到列表 | O(1) amortized |
| 进程限制 | 无 | 原子计数器 | <1μs |
| **安全级别 STRICT** | N/A | +命名空间设置 | +~20ms (unshare) |
| **安全级别 BASIC** | baseline | +安全检查 | +~50μs |

### 4.3 动态路由性能影响

| 操作 | 当前 | 改造后 | 差异 |
|------|------|--------|------|
| 路由决策 | 静态 dict lookup | env 配置解析 + 别名 | +~10μs |
| Fallback chain 构建 | 静态 dict | 运行时组合 | +~20μs |
| 熔断检查 | O(1) dict | O(1) dict | 无变化 |
| 健康检查 | 首次约 300ms | 维护缓存 | 但不会在热路径上重复 |
| **总体热路径延迟增加** | | | **< 100μs** |

### 4.4 工程质量保障

| 维度 | 当前状态 | 目标 |
|------|----------|------|
| 测试覆盖 | ~0% (这些模块) | >90% 核心逻辑 |
| 类型安全 | 大量 `Any` | 全类型标注 + mypy strict |
| 错误处理 | 静默失败 / 裸 `except` | 明确的错误层次 |
| 接口契约 | 无 Protocol / ABC | `Sandbox(Protocol)` + `RBAC(Protocol)` |
| 可观测性 | 无 | Prometheus metrics + structured logging |

---

## 5. 推荐执行顺序

### Phase 1 — 立即可做（~2 天）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 1.1 | 在 `security/` 下创建 `UnifiedRBAC`，合并两个 Permission 枚举 | `security/rbac.py` (重写) |
| 1.2 | 接入 `tools/registry.py` 执行点 | `tools/registry.py` |
| 1.3 | 更新 `test_security.py` 验证 | `tests/test_security.py` |

### Phase 2 — 沙箱统一（~2 天）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 2.1 | 将 `SecureSandbox` 改为装饰器模式，统一返回 `SandboxResult` | `sandbox/secure_sandbox.py` |
| 2.2 | 更新 `sandbox/__init__.py` 导出统一接口 | `sandbox/__init__.py` |
| 2.3 | 更新 `orchestrator.py` 使用新接口 | `runtime/orchestrator.py` |
| 2.4 | 删除死代码 `_posix_limits` | `sandbox/subprocess_sandbox.py` |

### Phase 3 — 动态路由（~1.5 天）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 3.1 | 创建 `DynamicModelRouter` | `llm/task_router.py` |
| 3.2 | 接入 `ReasoningRouter` + `ModelAliasRegistry` | `llm/reasoning.py`, `llm/model_aliases.py` |
| 3.3 | 更新 `l0_execution.py` 调用链 | `layers/l0_execution.py` |
| 3.4 | 暴露配置 API | `api/routers/llm.py` |

### Phase 4 — 清理（~1 天）

| 步骤 | 任务 |
|------|------|
| 4.1 | 标记旧类为 deprecated（保留向后兼容一个版本） |
| 4.2 | 删除 `governance/rbac.py` |
| 4.3 | 更新 `governance/__init__.py` |
| 4.4 | 全量测试 + 回归验证 |

**总计**: ~6.5 天

---

## 6. 风险与缓解

| 风险 | 概率 | 缓解措施 |
|------|------|----------|
| 统一 RBAC 破坏现有 API 客户端 | 低 | 保持旧 Permission 枚举的字符串值兼容（点号转冒号用别名） |
| 沙箱统一影响 L0 执行性能 | 低 | `SecurityLevel.NONE` 走零成本抽象路径，无安全检查 |
| 动态路由配置复杂化 | 中 | 提供合理的默认值，env 驱动 + API 覆盖 |
| `orchestrator.py` 上帝对象问题未解决 | 高 | 本次聚焦三点，上帝对象单独规划在 v0.6.0 |
