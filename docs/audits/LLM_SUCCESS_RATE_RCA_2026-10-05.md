# LLM 成功率 0% 根因分析（RCA）

**日期**: 2026-10-05
**现象**: 看板 LLM 成功率降为 0%（近 1h 实测 1/20 = 5%，多数窗口 0%）。
**结论**: **本地模型吞吐远低于链级 90s 预算** + **兜底链实际失效（被塌缩成单 provider）**；
叠加两处**可观测性缺陷**（空错误、零延迟）使故障长期不可诊断。

---

## 1. 定点排查过程与证据

| 步骤 | 命令/观测 | 结果 |
|------|-----------|------|
| 1 | `GET /api/v1/metrics/llm?window_s=3600` | `samples=7 success_rate=0.0`，tokens 全 0 |
| 2 | `GET /api/v1/metrics/llm/recent` | 失败 `error=''`、`latency_ms=0`，模型为 35B |
| 3 | 直连 LM Studio `/v1/chat/completions` | **HTTP 200**（上游健康，非模型名问题） |
| 4 | 直连 `max_tokens=64` 计时 | **>180s 未返回**（curl 超时）→ 模型极慢 |
| 5 | `GET /api/v1/llm/routing` | 绑定：code/council→**35B**；nlp/data→**9B** |
| 6 | 进程内探针（fallback=["lmstudio","ollama"]） | **lmstudio 调用 1 次，ollama 0 次** → 兜底链失效 |
| 7 | `str(asyncio.TimeoutError())` | `''` → 失败被记成空错误 |

---

## 2. 根因

### 2.1 主因：模型吞吐 ≪ 链级预算

`_effective_fallback_deadline = min(contract-5s, 90s)`，默认 `max_tokens=2048`。
本地 35B 推理模型连 64 token 都跑不完 180s → **每次调用必然在 90s 超时**。
9B 对小 prompt 可用（15.5s），但 **Council 大 prompt 下同样超 90s**。

### 2.2 结构性缺陷：兜底链被塌缩为单 provider

`LLMManager._apply_runtime_state` 返回 `effective_provider = provider or state.provider`；
state.provider 恒为 `lmstudio` → 调用点 `chain = [provider] if provider else list(self._fallback)`
得到**单元素链**，`self._fallback`（配置的 35B→9B→ollama）**永不生效**。
实测探针：`lmstudio` 调用 1 次、`ollama` **0 次** —— 超时后没有任何兜底机会。

### 2.3 可观测性缺陷：失败不可诊断

* `asyncio.TimeoutError` 的 `str()` 为空 → `error=''`；
* 失败路径硬编码 `latency_ms=0.0` → 看不到等了多久；
* 链级预算 90s **硬编码**，无法为慢模型放宽。

---

## 3. 已落地的修复（代码）

| 修复 | 位置 |
|------|------|
| `_exc_summary()`：超时命名为 `provider timeout after Nms`；空消息回退异常类型名 | `llm/manager.py` |
| 4 条失败路径记录**真实耗时**（原恒为 0） | `llm/manager.py` |
| `MORE_LLM_FALLBACK_DEADLINE_S` 可配置（默认 90） | `llm/manager.py` |
| 链级预算**公平分配**（剩余时间均摊给剩余 provider，避免慢首选饿死兜底） | `llm/manager.py` |
| 新增 4 个回归测试 | `tests/test_llm_fallback.py` |

### 修复前后（实机）

```
修复前:  lat=0ms     err=''
修复后:  lat=90078ms err='provider timeout after 90078ms'
         lat=15059ms err='cancelled (task timeout / client disconnect)'
```

---

## 4. 兜底链塌缩 —— 已修复

`_apply_runtime_state` 曾用 `state.provider` 覆盖未显式指定的 provider，使 `_fallback` 失效；
且 `state.model` 是 **provider 专属**模型名，若直接放开多 provider，会把 LM Studio 模型名强加给 ollama。

**修复（三处）**：

1. `_apply_runtime_state` 只应用 provider 无关覆盖（`temperature`/`max_tokens`），
   **不再**返回 provider 覆盖 → `chain` 恢复为完整 `self._fallback`。
2. 新增 `_resolve_request_for_provider(request, provider)`：**逐 provider** 解析生效模型，
   优先级 = 调用方 `model_override` > `state.model`（仅当该 provider == `state.provider`）> provider 默认模型。
3. `generate()` 循环内逐 provider 调用该方法；`state.provider` 仅作**偏好排序**（排链首，不删除其它兜底）。

**契约保持**：调用方显式传 `provider=` 仍 pin 单 provider（不走兜底）。

**验证**（进程内探针，fallback=["lmstudio","ollama"]，两者都必然失败）：

```
修复前: lmstudio calls: 1  | ollama calls: 0     ← 链被塌缩
修复后: lmstudio calls: 1  | ollama calls: 1     ← 两条都真正执行
        lmstudio 收到 state.model('...35b')；ollama 收到 None（用自己的默认模型）
```

### 建议的运维缓解（无需改码，可立即执行）

| 措施 | 命令 |
|------|------|
| 放宽链级预算 | 启动时设 `MORE_LLM_FALLBACK_DEADLINE_S=300` |
| 降低单次输出预算 | `POST /api/v1/llm/state/update {"max_tokens": 256}` |
| 对慢模型路径改用轻量模型 | `POST /api/v1/llm/state/update {"model":"ornith-ai/ornith-1.5-9b"}` |
| 提升本地推理性能 | 检查 LM Studio 显存/量化设置（35B 明显超出实时能力） |

---

## 5. 配置修复（已写入 more_core/.env）

在代码修复之外，落地了运维配置（备份：`more_core/.env.bak.20261005`）：

| 配置 | 值 | 作用 |
|------|-----|------|
| `MORE_LLM_FALLBACK_CHAIN` | `ollama,lmstudio` | **把已验证可用的 7B 排到链首**，消除 35B 白耗 150s |
| `MORE_OLLAMA_TIMEOUT` | `240` | Ollama 大 prompt 需 ~118s，原硬编码 120s 太紧 |
| `MORE_LLM_FALLBACK_DEADLINE_S` | `300` | 链级预算 90s → 300s |
| `MORE_LLM_MAX_TOKENS` | `512` | 单次输出 2048 → 512，避免耗尽预算 |

配套代码改动：`MORE_OLLAMA_TIMEOUT` / `MORE_LMSTUDIO_TIMEOUT` 可配（原硬编码 120s）；
`MORE_LLM_MAX_TOKENS` 在 bootstrap 初始化 state manager。

### 实测效果（写入后）

| 指标 | 修复前 | 写入配置后 |
|------|:---:|:---:|
| 生效 provider | lmstudio/35B（必超时） | **ollama/qwen2.5:7b** |
| `ollama:qwen2.5:7b` 成功率 | —（从不执行） | **连续 11 次全成功**（真实产出 ct=367~512） |
| 整体 LLM 成功率（30min） | 0% | **40.8%** |
| 失败原因可读性 | `err=''` | `provider timeout after 150094ms` |

### 5.1 重负载任务降载（已修复）

Council 默认 5 角色 × (独立+交叉) + 综合 ≈ **11 次 LLM 调用**，串行阶段撑爆任务预算。
另发现两条路径**绕过全局预算**：`generate_with_fallback_chain` / `generate_parallel`
不经 `_apply_runtime_state`，L1 的 `max_tokens=8192` 直打慢模型，单次 130–224s。

**修复**：

| 修复 | 位置 |
|------|------|
| Council 降载旋钮：`max_roles` 截断角色数；`enable_cross_review=False` 跳过 Stage 2 | `council/orchestrator.py` |
| 旋钮 env 化：`MORE_COUNCIL_MAX_ROLES` / `MORE_COUNCIL_CROSS_REVIEW` | `runtime/bootstrap.py` |
| **全局 max_tokens 封顶**：chain / parallel 入口也遵守（原绕过） | `llm/manager.py` |
| 逐层模型覆盖：`MORE_TIER_{0..3}_MODEL` 把最慢的 T0 换成可用模型 | `more_core/.env` |

**配置**：`MORE_COUNCIL_MAX_ROLES=3`、`MORE_COUNCIL_CROSS_REVIEW=0`、
`MORE_TIER_0_MODEL=ollama:qwen2.5:7b`（T1/T2→9B，T3→7B）。

### 5.2 最终实测

| 指标 | 修复前 | 最终 |
|------|:---:|:---:|
| 高难度任务 | 280s **超时失败** | **85.8s 成功产出** |
| 近 10min LLM 成功率 | 0% | **90%**（`ollama:qwen2.5:7b` **9/9=100%**） |
| 单次调用 max_tokens | 8192（无上限） | 512（全局封顶） |
| Council 调用数 | 11 | 4（3 角色 + 综合） |
| 唯一残留失败 | — | 修复前的历史 224s 调用（不再复现） |

---

## 6. 变更文件

- `more_core/more_core/llm/manager.py` — 失败诊断 + 可配置预算 + 公平分配 + **兜底链去塌缩**
- `more_core/more_core/runtime/bootstrap.py` — `MORE_LLM_MAX_TOKENS` 初始化生效 state
- `more_core/more_core/core/config.py` — `MORE_OLLAMA_TIMEOUT` / `MORE_LMSTUDIO_TIMEOUT` 可配
- `more_core/more_core/council/orchestrator.py` — `max_roles` / `enable_cross_review` 降载旋钮
- `more_core/more_core/llm/manager.py` — chain/parallel 入口全局 max_tokens 封顶
- `more_core/tests/test_council_adaptive_sizing.py` — 3 个降载用例
- `more_core/tests/test_llm_fallback.py` — 追加封顶用例
- `more_core/tests/conftest.py` — 隔离开发者本地 `.env` 的 LLM 调优（空串占位阻止 dotenv 灌入）
- `more_core/more_core/core/config.py` — `int(os.getenv(...) or "120")` 空值安全
- `more_core/tests/test_llm_fallback.py` — 8 个回归用例（诊断 3 + 去塌缩 4 + 公平分配 1）
- `more_core/tests/test_bootstrap.py` — 2 个 env 用例
- `more_core/.env` — 链序 / 超时 / 预算 / max_tokens（含备份）

*执行人: Codex · 2026-10-05*
