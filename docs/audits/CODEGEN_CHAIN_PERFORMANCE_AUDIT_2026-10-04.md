# MoRE OS 代码生成业务链路 — 功能审计与产出性能评估

**审计日期**: 2026-10-04
**审计版本**: v0.9.9（工作区 `main` + 未提交改动）
**被测实例**: API `127.0.0.1:8011`（`llm_providers=lmstudio`，`codegen.candidates=1`，`codegen.review=false`）
**审计重点**: 代码生成业务链路的功能正确性 + **代码产出性能**（延迟 / token / 正确率 / 吞吐）
**审计方式**: 全链路代码走读 + 运行时端到端基准（真实调用 LM Studio）+ 独立正确性复验

---

## 1. 结论速览

| 维度 | 评价 | 关键证据 |
|------|:----:|----------|
| 链路完整性 | ✅ 完整 | L4→L1→L0 + 模板分派双通路，均有终态与交付 |
| **产出正确性** | ❌ **差** | 严格功能正确率 **1/4 = 25%**，但平台自报 100% pass |
| **交付可信度** | ❌ **严重** | 沙箱验证通过的是 A，交付给用户的是被过滤器改坏的 B |
| **延迟性能** | ⚠️ **差** | 同类任务 3.7s ~ 228.3s，**波动 62×** |
| **成本性能** | ⚠️ 中 | k=1 ≈ 3.2–3.6k token；best-of-2 ≈ **2.9–3.1×** token |
| **模板通路产出** | ❌ **无实际代码** | cs_shooter 29 文件仅 4,953 字符、7 处 `placeholder` |
| **可观测性** | ❌ **完全失效** | 遥测模块导入错误，**0 条 LLM 调用记录持久化** |
| 路由准确性 | ❌ 差 | `docs/metrics/statistics/specs/fps` 均被误判为 CS 射击任务 |

**一句话结论**: 代码生成链路的"骨架"（分层、最优候选、修复回环、评审面板、控制器裁决）设计相当完整，
但**产出质量与交付可信度存在硬伤**：输出过滤器会破坏生成的代码、模板通路只产出空壳、
且平台自身的性能遥测完全不工作——导致"产出性能"无法被系统自我度量。

---

## 2. 链路全景

### 2.1 两条互不相同的"代码生成"通路

```
通路 A — 模板/原生（零 LLM）
  POST /tasks/itd/import ──▶ SQLiteTaskStore(父+REQ子任务)
  POST /tasks/{id}/execute ─▶ _execute_task_background_v2
        └▶ TemplateDispatcher.dispatch()
              ├─ TaskTemplateSelector.key_for()   ← 关键词正则分流
              ├─ plan_for_key()                   ← 规则化 Step 列表
              └─ TaskPayloadTemplateRegistry.get(key).build_payload_map()  ← 硬编码文件内容
        └▶ Writer.apply()（白名单写盘）▶ Validator(cargo)▶ Delivery(打包)

通路 B — LLM 代码生成
  POST /tasks/execute ─▶ orchestrator.execute()
        └▶ L4(认知/难度) ─▶ L1(策略/温度) ─▶ L0
              ├─ _do_generate()                 ← LLM 生成（含 fallback 链）
              ├─ _select_best_candidate(k)      ← best-of-k（串行）
              ├─ _run_candidate → python_exec    ← 沙箱执行
              ├─ _run_fix_loop(max 3 rounds)     ← 失败回灌修复
              ├─ _gate_review()                  ← 三角色评审面板（并行，默认关）
              └─ adjudicate_codegen()            ← 确定性控制器裁决
        └▶ OutputFilter.filter(output)           ★★ 交付前改写 ★★
        └▶ TaskResult(status=success, output=…)
```

### 2.2 关键参数

| 项 | 值 | 位置 |
|----|----|------|
| 最大修复轮次 | 3 | `l0_execution._MAX_CODE_FIX_ROUNDS` |
| best-of-k 上限 | 见 `_MAX_CODE_CANDIDATES`，默认基础 2 | `_candidate_k()` |
| 单次 LLM 截止 | 90s 上限 | `llm/manager._effective_fallback_deadline` |
| 评审角色 | 3（correctness/security/quality），`asyncio.gather` 并行 | `codegen/review.py` |
| 答案缓存 TTL | 300s | `llm/manager._CACHE_TTL_S` |
| 任务级结果缓存 | 无 TTL 显式设置（默认 3600s） | `orchestrator.execute` + `RequestCache` |

---

## 3. 实测产出性能

### 3.1 基准方法

- 4 个可客观判定的 Python 任务：`is_prime` / `merge_intervals` / `LRUCache` / 账户模块
- 每个任务经 `/api/v1/tasks/execute` 真实执行（LM Studio 本地模型）
- **独立复验**：把返回的代码块抽出，追加断言后本地 `python` 运行，判定功能正确性
- 用 `[ref:nonce]` 绕过任务级缓存，保证测量的是真实执行

### 3.2 延迟与成本

| 任务 | k=1 延迟 | k=1 token | k=2 延迟 | k=2 token | token 放大 |
|------|---------:|----------:|---------:|----------:|-----------:|
| is_prime | 3.7s | 3,200 | 5.7s | 9,927 | 3.10× |
| merge_intervals | 5.1s | 3,267 | 7.7s | 10,257 | 3.14× |
| LRUCache | **228.3s** | 3,643 | 102.9s | 10,767 | 2.96× |
| 账户模块（首轮） | 19.2s | 4,162 | —（缓存命中） | — | — |
| merge（轨迹复测） | 6.8s | 3,377 | 4.8s | 9,753 | 2.89× |

派生指标：

| 指标 | k=1 | k=2 |
|------|----:|----:|
| 延迟中位数 | ≈ 5.9s | ≈ 6.7s |
| 延迟极差（同链路同类任务） | 3.7 → 228.3s (**62×**) | 4.8 → 102.9s (**21×**) |
| token/任务区间 | 3,200 – 4,162 | 9,753 – 10,767 |
| 有效吞吐区间 | 16 – 865 tok/s | 105 – 1,742 tok/s |
| 首包即通过（无修复回环） | 是（merge/trace） | 是 |

> **注意吞吐的误导性**：`tokens/wall` 在快任务上看起来很高（生成快），
> 但 LRUCache 的 k=1 只用了 3,643 token 却耗时 228.3s → **有效吞吐仅 16 tok/s**。
> 说明**瓶颈不在模型生成速度，而在超时/重试/修复轮次的等待**。

### 3.3 产出正确性（k=1，部署配置）

| 任务 | 平台状态 | 平台裁决 | 独立复验 | 失败原因 |
|------|:--------:|:--------:|:--------:|----------|
| is_prime | success | pass | ✅ 通过 | — |
| merge_intervals | success | pass | ❌ 失败 | **交付代码被过滤器破坏**（见 F-01） |
| LRUCache | success | pass | ❌ 失败 | 语义/接口不符（断言失败） |
| 账户模块 | success | pass | ❌ 失败 | 接口不符（构造函数签名） |

**严格功能正确率 = 1/4 = 25%**，而平台自报 **4/4 success + verdict pass**。

### 3.4 模板通路产出（通路 A）

| 模板 | 文件数 | 总字符 | placeholder 数 | 分派耗时 |
|------|-------:|-------:|---------------:|---------:|
| `tetris` | 13 | 38,259 | 0 | 0.2ms |
| **`cs_shooter`** | **29** | **4,953** | **7** | 0.1ms |
| `generic` | 7 | 434 | 0 | 0.0ms |

`cs_shooter` 的实际内容（节选）：

```rust
// shooter_server/src/main.rs
fn main(){ println!("shooter server placeholder"); }
```

```rust
// shooter_bot/src/lib.rs
//! Heuristic bot logic placeholder.
```

```tsx
// frontend/src/App.tsx
export const App: React.FC = () => <div>CS Shooter (placeholder)</div>;
```

结论：**cs_shooter 通路不生成代码，只生成"文件名正确"的空壳**（29 文件平均 171 字符/文件）。
分派仅 0.1ms 是因为**完全没有调用 LLM**——它不是"高性能"，而是"没有做生成"。

---

## 4. 关键发现

### F-01 🔴 输出过滤器破坏生成的代码（最高优先级）

`security/output_filter.py:77` 的 `env_secret` 规则：

```python
re.compile(r"(?:PASSWORD|SECRET|TOKEN|KEY)\s*=\s*\S+", re.IGNORECASE)
```

它会命中**任何**以 `key=` / `token=` / `password=` / `secret=` 开头的 Python 关键字参数或赋值，
并且 `\S+` 会贪婪吞掉后续 token。

实测（真实交付样本）：

```python
# 原始（有效）
sorted_intervals = sorted(intervals, key=lambda x: x[0])
# 交付给用户的（无效）
sorted_intervals = sorted(intervals, [ENV_SECRET_REDACTED] x: x[0])
```

更多复现：

| 原始 | 过滤后 |
|------|--------|
| `sorted(items, key=lambda x: x[0])` | `sorted(items, [ENV_SECRET_REDACTED] x: x[0])` |
| `def f(key=1, token=None): pass` | `def f([ENV_SECRET_REDACTED] [ENV_SECRET_REDACTED] pass` |
| `redis.set(key=user_id, value=data)` | `redis.set([ENV_SECRET_REDACTED] value=data)` |
| `key = self._key(prompt, model)` | `[ENV_SECRET_REDACTED] model)` |

**影响面量化**：把该规则应用到 MoRE 自身源码，**135 行 / 49 个文件**会被改写（占全部行 0.31%）——
`optimization.py`、`incident_response.py`、`cli.py` 等均在其中。

**根因**：`orchestrator.py:555` 对**所有**任务输出无条件调用
`self.output_filter.filter(str(output))`，没有针对 `type=code_generation` 的旁路。

---

### F-02 🔴 验证与交付对象不一致（验证 A、交付 B）

L0 的沙箱验证针对**原始 LLM 输出**；`output_filter` 在**返回给调用方之前**才改写。
两者不是同一个工件，于是出现：

```
L0 沙箱执行原始代码 → 语法正确 → 裁决 pass
        ↓
OutputFilter 改写 → 语法被破坏 → 交付给用户
        ↓
TaskResult.status = "success"，caller 收到无法编译的代码
```

实测：merge 任务的 `py_compile` 返回 **rc=1 / SyntaxError**，而该任务
`status=success`、`metadata.codegen_verdict.decision="pass"`、trace 含 `code executed`。

---

### F-03 🔴 可观测性完全失效 → 无法系统化度量产出性能

`governance/observability.py:162`：

```python
from .config import Settings as _S   # ✗ more_core.governance.config 不存在
```

正确路径应为 `..core.config`。该 ImportError 被 `_get_conn()` 的
"Silently no-ops on any failure" 设计吞掉，导致：

- `record_llm_call()` / `record_injection()` **全部静默丢弃**
- 全仓库**不存在** `logs/observability.sqlite`（即使已执行数十次 LLM 调用）
- `/api/v1/health` 的 `recent_llm_success_rate` 恒为 `0.0`、`injection_counts_1h` 恒为空

**影响**：平台无法回答"本次代码生成用了多少 token、多长延迟、哪家 provider 成功"，
也没有可供 L2 自进化消费的真实性能信号。

---

### F-04 🔴 模板路由正则缺少词边界，误判率高

```python
CS_RE = r"(?i)(cs|shooter|射击|fps|第一人称|counter.?strike)"
```

`cs` 与 `fps` 都是**裸子串**匹配，实测误判：

| 输入 | 被路由到 |
|------|----------|
| 补充项目 **docs** 文档 | `cs_shooter` ❌ |
| 导出 Prometheus **metrics** 指标 | `cs_shooter` ❌ |
| 写一个 **statistics** 统计模块 | `cs_shooter` ❌ |
| 更新 API **specs** 说明 | `cs_shooter` ❌ |
| 优化视频解码，把 **fps** 从 30 提到 60 | `cs_shooter` ❌ |
| 统计日志里 **fps** 关键字出现次数 | `cs_shooter` ❌ |

即：任何含 `cs` 子串（docs/metrics/statistics/specs）或 `fps` 字样的任务，都会拿到**射击游戏空壳工程**。

---

### F-05 🟠 任务级结果缓存使"重生成"失效，并绕过治理

`orchestrator.py:342` 缓存键 = `task_type + sha256(query)`：

- 相同 query 第二次请求：实测 **0.0s / 0 token** 直接返回历史结果
- 对代码生成而言这意味着**无法重新生成/迭代**（用户修改了上下文但 query 未变时仍拿到旧代码）
- 缓存命中分支位于 ZEN 规则与 `policy.check()` **之前**，且不含 `actor`，存在跨主体复用（详见前轮审计 AUD-09）

---

### F-06 🟠 best-of-k 串行执行，成本线性放大

`l0_execution._select_best_candidate()`：

```python
for _ in range(k):
    in_tok, out_tok, content = await self._do_generate(...)   # ← 串行
    results.append(await self._run_candidate(...))
```

- 延迟：k 次串行生成（未能利用同实例并发），仅在 *provider 竞速*
  （`LLMManager.generate_parallel` 的 race-to-first）上有并行，但那不适合需要**多样性**的 best-of-k
- 成本：实测 **2.89× – 3.14× token**（k: 1→2）
- 收益：本组基准中未观察到正确率提升（两个 config 下 merge 均因 F-01 而交付失败）

---

### F-07 🟠 成功判据过宽："能跑不报错"即 pass

控制器 `checks` 实测：`{"sandbox": true, "assertions": false, ...}`。
`adjudicate_codegen` 仅在"显式要求断言"时才检查 `assertions`；默认任务
`assertions_required=false` → **只要代码不抛异常即 pass**，
不校验功能是否满足任务描述。这直接解释了"100% pass / 25% 功能正确"的落差。

---

### F-08 🟡 重复裁决与噪声信号

- `l0_execution.py` 在 ~505 行与 ~586 行**重复调用** `adjudicate_codegen(...)`（完全相同参数），
  结果只保留后者；属冗余计算（当前确定性、开销小，但会随裁决逻辑变重而放大）。
- `convergence_report.state` 对 `is_prime` 这种平凡任务也报 `oscillating` 且
  `divergence_detected=true`（4 次快照完整性恒为 0.5），信号噪声大，难以作为质量门禁。

---

## 5. 瓶颈定位（按影响排序）

| 排名 | 瓶颈 | 量化影响 | 性质 |
|:---:|------|----------|------|
| 1 | 输出过滤器改写代码 | 25% → 破坏交付物；自身源码 135 行受影响 | **正确性/可信度**（非性能） |
| 2 | 修复回环 + 90s 截止叠加 | 单任务最坏 ~3×90s + 重试 → 实测 228.3s | **延迟尾部** |
| 3 | best-of-k 串行 | k=2 时 token ×2.9–3.1 | **成本** |
| 4 | 任务级缓存短路 | 重生成 0 收益；基准被污染 | **可测试性/治理** |
| 5 | 路由误判 | 命中即产出空壳工程（4,953 字符） | **功能正确性** |
| 6 | 遥测缺失 | 无法量化任何生产性能指标 | **可观测性** |

延迟分布特征：**中位数 ~5-7s 良好，但尾部高达 102–228s**。
尾部由"修复轮次 × 单轮 LLM 截止（90s）"决定，而不是由 token 吞吐决定
（LRUCache k=1：3,643 token / 228.3s = 16 tok/s）。

---

## 6. 优化建议

### P0（正确性与可信度，先修）

1. **代码类任务旁路输出过滤器**
   `orchestrator.py:555` 增加条件：`request.type in {CODE_GENERATION, CODE_DEBUGGING, CODE_TESTING}`
   时跳过 PII 改写，或仅对"密钥字面量"（带引号的 `sk-…`/`ghp_…`）做定向脱敏。
2. **收紧 `env_secret` 规则**
   改为要求引号且长度下限，例如
   `r"(?i)\b(PASSWORD|SECRET|TOKEN|API_KEY|ACCESS_KEY)\b\s*[=:]\s*['\"][^'\"]{12,}['\"]"`，
   并加负向断言排除 `key=`/`token=` 后跟标识符的 Python 形参。
3. **验证与交付同源**
   把 `output_filter` 前移到沙箱验证**之前**（先过滤再验证），
   或对过滤后的产物**重新执行一次**验证，杜绝"验 A 交 B"。
4. **修复遥测导入**
   `observability.py:162` → `from ..core.config import Settings`，
   并增加一条"写入后能读回"的冒烟测试（当前完全无覆盖）。

### P1（性能与成本）

5. **best-of-k 并行化**
   用 `asyncio.gather` 同时发起 k 次生成（独立性由采样温度保证），
   预期 k=2 的墙钟时间从 ~2× 降到 ~1×，代价是并发占用；同时用 token 预算上限做熔断。
6. **给修复回环加总预算**
   目前是"最多 3 轮 × 每轮 90s"。建议改为**整任务总预算**（如 120s），
   轮次内动态分配，避免 228s 长尾。
7. **任务级缓存加维度与 TTL**
   缓存键纳入 `actor` + 影响执行的 context 字段；对代码生成类任务默认关闭或 TTL 极短；
   并把 `policy.check()` 提到缓存查询之前。

### P2（工程质量）

8. **修模板路由正则**：加词边界与整词匹配，如
   `r"(?i)\b(cs|shooter|counter.?strike)\b|射击|第一人称|fps\b"`，
   并优先使用 ITD frontmatter 的 `type/tags` 而非自然语言子串。
9. **cs_shooter/generic 模板接入 LLM 填充**
   模板只定"文件清单与骨架"，内容由 LLM 生成并经沙箱验证——
   即把通路 A 与通路 B 合并，避免"文件名正确但内容是 placeholder"。
10. **去重 `adjudicate_codegen` 调用**，并把 `convergence_report` 的
    completeness 计算改为可区分的指标（当前恒 0.5 导致噪声）。

---

## 7. 附录：复现命令

```bash
# 1) 探针：单次代码生成（观察 status/success、verdict、token）
.venv/bin/python - <<'PY'
import subprocess, httpx, json
k=subprocess.run("grep -E '^MORE_API_KEY=' more_core/.env | head -1 | cut -d= -f2-",
                 shell=True,capture_output=True,text=True).stdout.strip()
r=httpx.post("http://127.0.0.1:8011/api/v1/tasks/execute",
  headers={"Authorization":f"Bearer {k}"},
  json={"type":"code_generation","query":"写一个 Python 函数 merge_intervals 合并重叠区间",
        "timeout_s":120,"context":{"candidates":1}}, timeout=300)
d=r.json(); print(d["status"], d["performance"]["tokens_used"])
print((d.get("metadata") or {}).get("codegen_verdict"))
print(d["output"][:400])
PY

# 2) 复现 F-01：过滤器破坏代码
.venv/bin/python -c "
import sys; sys.path.insert(0,'more_core')
from more_core.security.output_filter import OutputFilter
print(OutputFilter().filter('sorted(items, key=lambda x: x[0])'))"

# 3) 复现 F-04：路由误判
.venv/bin/python -c "
import sys; sys.path.insert(0,'more_core')
from more_core.core.native_executor.planner import TaskTemplateSelector as T
from types import SimpleNamespace as S
for q in ['补充 docs 文档','导出 metrics 指标','统计 fps']:
    print(q,'->',T().key_for(S(query=q),None))"

# 4) 复现 F-03：遥测导入错误
.venv/bin/python -c "
import sys; sys.path.insert(0,'more_core')
from more_core.governance import observability as ob
ob._get_conn()"     # ModuleNotFoundError: more_core.governance.config
```

---

*审计人: Codex · 2026-10-04 · 全链路走读 + 端到端基准 + 独立正确性复验*
