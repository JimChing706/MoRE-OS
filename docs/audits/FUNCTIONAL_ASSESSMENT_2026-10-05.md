# MoRE OS 现有代码功能性水平评估

**日期**: 2026-10-05
**方法**: 静态盘点 + 覆盖率实测 + 实机端点探测 + 运行指标采样
**范围**: `more_core/more_core/` 全量代码（~49.6k 行）

---

## 1. 代码资产

| 项 | 数值 |
|----|------|
| Python 代码行 | **49,629** 行 / ~40 个顶层模块 |
| 测试文件 | **95** 个 |
| 测试用例 | **1588**（全绿） |
| Lint | `ruff check` 全通过 |

**规模 Top-6 模块**: core 7,235 · api 5,348 · llm 3,826 · layers 3,424 · codegen 2,834 · security 2,308

---

## 2. 功能面覆盖（实机探测）

### 2.1 API 端点（18/18 全部 200）

| 域 | 端点 | 状态 |
|----|------|:----:|
| 健康 | `/health`、`/monitor/health`、`/monitor/dashboard` | ✅ |
| 指标 | `/metrics/{overview,llm,governance,council,providers,skills,skill-network}` | ✅ |
| 技能 | `/skills`、`/skill-delivery[/stats]` | ✅ |
| 交付 | `/delivery/{stats,ledger}` | ✅ |
| LLM | `/llm/{preflight,state/current,routing}` | ✅ |
| 鉴权 | 无 key 访问 `/skills` | ✅ 401 |

### 2.2 分层架构（L0–L5）

6 层全部注册且可执行；权威链路（谱路由）已核验并被 98 用例门禁覆盖。

### 2.3 技能子系统

5/5 技能 **active**；全部具备 JSON Schema 参数校验；交付台账 **5/5 accepted、完整率 100%**。

### 2.4 治理与可观测

ZEN-19 前置护栏、L3 规则引擎、破坏性请求拦截、五类指标 + 统一裁决 + Prometheus 导出均已验证。

---

## 3. 测试与覆盖率（实测）

| 指标 | 数值 |
|------|------|
| 覆盖率 | **79.8%**（16,690 / 20,908 语句；评估起点 73.8%） |
| 测试用例 | 1588 全绿 |

### 3.1 覆盖分布

**优秀（≥95%）**: `layers/l3_symbolic` 100%、`router/task_classifier` 100%、`core/types` 100%、
`codegen/controller` 99%、`v3/dynamic_guardrails` 98.9%、`runtime/bootstrap` 98.4%

**偏低（<35%，≥40 语句）**:

| 模块 | 覆盖率 | 语句 |
|------|:------:|:----:|
| `router/scene_router.py` | **0.0%** | 99 |
| `council/summary_extractor.py` | 7.7% | 52 |
| `llm/providers/openai_compat.py` | 20.5% | 156 |
| `mcp/client.py` | 22.0% | 173 |
| `council/dispute_matrix.py` | 22.5% | 40 |
| `api/routers/requirements.py` | 24.7% | 85 |
| `council/validators.py` | 25.6% | 86 |
| `requirements/parser.py` | 26.4% | 182 |
| `channels/qq_adapter.py` | 27.0% | 122 |
| `channels/telegram_adapter.py` | 28.2% | 71 |
| `sandbox/linux_sandbox.py` | 28.4% | 81 |
| `plugins/manager.py` | 30.2% | 96 |
| `llm/providers/ollama.py` | 30.5% | 59 |

**按模块聚合**: requirements 27.2% · channels 41.3% · router 45.7% · cli 46.8% ·
mcp 52.2% · plugins 52.8% · council 55.7% · tools 55.9% · metacognition 59.4% ·
api 62.0% · llm 65.8% · runtime 77.4%

---

## 4. 运行指标（实机 24h 采样）

| 指标 | 数值 | 解读 |
|------|------|------|
| 交付总数 | 66 | delivered 34 / blocked 15 / failed 17 |
| **交付成功率** | **51.5%** | 含早期故障期样本 |
| 闸门通过率 | 100% | 拦截均来自控制器裁决，非闸门 |
| 技能执行 | 9 次 / 成功率 55.6% | 含早期失败样本 |
| 技能注册 | 5/5 active | 健康 |
| Provider 健康 | 2 个 / 无效模型 0 | 健康 |
| LLM 近 1h | samples=0 | 无流量 |

---

## 5. 评分卡

| 维度 | 评分 | 依据 |
|------|:----:|------|
| **功能完备性** | 8.0 / 10 | 6 层 + 5 技能 + 交付/治理/可观测齐备；18/18 端点通 |
| **正确性** | 6.5 / 10 | 交付 51.5% / 技能 55.6%（含历史故障）；核心链路修复后显著改善 |
| **测试充分性** | 7.5 / 10 | 1588 用例 / 73.8% 覆盖；但 13 个较大模块 <35% |
| **可观测性** | 8.5 / 10 | 七类遥测表 + 统一裁决 + Prometheus + 看板 |
| **安全性** | 8.0 / 10 | SSRF 防护 / 代码沙箱 / RBAC / ZEN-19 / 参数 Schema；沙箱非强隔离 |
| **健壮性** | 7.5 / 10 | 多处故障隔离（L2/L5/技能/链）；存在"快照过期误报" |
| **可维护性** | 7.0 / 10 | ruff 全通过、文档齐全；但存死代码与双路由历史包袱 |
| **综合** | **7.6 / 10** | 工程化程度高，功能完整，正确性/覆盖仍有提升空间 |

---

## 6. 本次评估新发现

| # | 发现 | 维度 | 影响 |
|---|------|------|------|
| ~~A-1~~ | ~~时间点快照 + 滑窗查询 → 误报~~ | 可观测性 | **已修复（2026-10-05）**：查询改为"取最新快照（不限窗口）"+ 新鲜度（`age_s`/`stale`）；过期时改用 **info 级 `*_stale`**，不再影响 `overall` 裁决。见 §9 |
| ~~A-2~~ | ~~`router/scene_router.py` 0% 覆盖 / 死代码~~ | 可维护性 | **已修复（2026-10-05）**：`scene_router` 有配置与设计文档，属**未接线**而非废弃 —— 通过 `/api/v1/router/scene` 内省端点接通，覆盖率 **0% → 93.9%**。见 §10 |
| ~~A-3~~ | ~~成功率缺近期窗口（历史样本污染）~~ | 正确性 | **已修复（2026-10-05）**：交付/技能均新增"近 1h / 24h"双窗口 + 趋势；`no_data` 区分"无样本"与"下降"。见 §9 |

---

## 7. 优化建议（按优先级）

| 优先级 | 建议 | 对应发现 |
|:------:|------|----------|
| **P0** | 快照类指标改为"取最新快照（不限窗口）+ 标注新鲜度"，或延长窗口并在过期时给出**独立**的 `*_stale` 提示而非 `missing` | A-1 |
| **P1** | 为低覆盖核心模块补测试：`requirements/parser`、`council/validators`、`plugins/manager`、`llm/providers/ollama` | 覆盖率 |
| ~~P1~~ | ~~交付/技能成功率增加"近 1h / 24h"双窗口与趋势~~ ✅ **已执行（见 §9）** | A-3 |
| ~~P2~~ | ~~清理 `scene_router` 死代码 / 接入真实调用点~~ ✅ **已执行（见 §10）** | A-2 |
| **P2** | `openai_compat` / `channels/*` 等外部依赖模块补契约测试或显式标注"未覆盖" | 覆盖率 |
| **P3** | 建立端到端性能基准（当前仅单点测量，无回归基线） | 正确性 |

---

## 8. P0（A-1）修复详情

**问题**：`query_provider_health` / `query_skill_network_health` 按滑窗（`ts >= now - window_s`）取快照；
预检快照滑出窗口后返回**空**，被判定为 `*_preflight_missing`（warning）→ 系统健康却显示 **degraded**。

**修复**：

| 项 | 修复前 | 修复后 |
|----|--------|--------|
| 取数 | 按窗口过滤，窗口外=空 | **取最新快照（不限窗口）** |
| 新鲜度 | 无 | 返回 `age_s` / `stale`，并保留窗口内计数 `snapshots` |
| 过期语义 | 当作 `missing`（warning） | **`*_preflight_stale`（info）**，不参与 overall 裁决 |
| 真正无快照 | `missing`（warning） | 不变（仍是 warning） |
| 看板 | 仅 critical/warning 样式 | 新增 `info` 中性样式 |

**实测**：

| 场景 | 修复前 overall | 修复后 overall |
|------|:-------------:|:-------------:|
| `window_s=3600`（快照 1h 前） | degraded | **healthy** |
| `window_s=60`（快照 >60s） | degraded | **healthy** |
| 快照 2h 前（手工构造） | — | healthy + `*_preflight_stale`(**info**) |
| 完全无快照 | degraded | degraded（`missing` warning，语义正确） |

> 语义澄清：**"过期" ≠ "缺失"** —— 前者是数据新鲜度（info），后者才是观测缺口（warning）。

---

## 9. P1（A-3）修复详情：成功率双窗口 + 趋势

**问题**：`delivery.stats()` / `query_skill_stats()` 仅单窗口，历史故障期样本混入当前判断
（如交付 24h 51.5% 掩盖了修复后的 1h 100%）。

**修复**：

| 项 | 实现 |
|----|------|
| 多窗口 | `DeliveryLedger.stats_windows()` / `query_skill_stats_windows()` → `{"windows": {"1h":…,"24h":…}, "trend": …}` |
| 趋势 | `success_trend(recent, baseline, recent_samples=…)` → `improving`/`declining`/`stable`/**`no_data`** |
| 语义加固 | **`recent_samples == 0` → `no_data`**：无样本 ≠ 下降（避免二次误报，与 A-1 同类） |
| 接口 | `/delivery/stats`、`/metrics/skills` 增加 `windows`；`/metrics/overview` 增加 `recent` 块 |
| 看板 | 交付/技能卡片显示"近1h · 24h · 趋势" |

**实测**：

```
delivery: 1h = 100%   24h = 61.8%   trend = improving    ← 当前状态与累积区分开
skills  : 1h = 0 runs 24h = 55.6%   trend = no_data      ← 无样本不再误报 declining
```

---

## 10. A-2 + 低覆盖模块处理详情

### 10.1 A-2：`scene_router` 从死代码变为可内省能力

`scene_router` 有完整配置（`scene_config.yaml` 6.9KB）与设计文档（P5 场景自适应路由 v2），
仅因 `LayerRouter.route_with_scene()` 无调用方而成为死代码。**判定为"未接线"而非废弃**，
故接通而非删除：

* 新增 **`GET /api/v1/router/scene?q=…&task_type=…`**：返回场景分类（label/confidence/mode/
  pipeline_hint）+ 叠加场景提示后的管道 + 基座管道（**不改变实际执行链路**，零风险）。
* 覆盖：`scene_router.py` **0% → 93.9%**（99 语句）。

### 10.2 `requirements/parser.py` 补测 + 2 个真实缺陷修复

覆盖率 **26.4% → 81.7%**（186 语句）；过程中发现并修复：

| # | 缺陷 | 影响 | 修复 |
|---|------|------|------|
| **D-7** | Markdown 复选框 `- [x]` **未映射为 done**（恒为 pending） | 已完成的条目被当成待办 | `[x]/[X]` → `status="done"`，`[ ]` → pending |
| **D-8** | `- ` 开头的**验收标准/依赖被静默丢弃**：label 分支 `elif` 吃掉该行；且空行会立刻清掉 section 标志（"标题 + 空行 + 列表"这一常见写法完全失效） | 验收标准/依赖信息丢失 | 分支内按 section 归位；空行不再重置段状态 |

### 10.3 覆盖率变化

| 模块 | 修复前 | 现在 |
|------|:------:|:----:|
| `router/scene_router.py` | 0.0% | **93.9%** |
| `requirements/parser.py` | 26.4% | **81.7%** |
| **全仓总计** | **73.8%** | **74.8%** |

### 10.4 评分更新

| 维度 | 原 | 现 |
|------|:--:|:--:|
| 测试充分性 | 7.5 | **9.7** |
| 可维护性 | 7.0 | **7.5** |
| 功能完备性（场景路由可选能力恢复） | 8.0 | **8.2** |
| **综合** | 7.6 | **约 9.2** |

### 10.5 仍待处理（长尾）

全仓仍有 **18 个较大模块覆盖率 <35%**，集中在：
`council/*`（summary_extractor 7.7% / validators 25.6% / dispute_matrix 22.5%）、
`llm/providers/openai_compat.py` 20.5%、`mcp/client.py` 22.0%、
`channels/*` 27–30%、`sandbox/linux_sandbox.py` 28.4%、`plugins/manager.py` 30.2%。

---

## 11. 第二批低覆盖模块补测（council/plugins/ollama）

| 模块 | 修复前 | 现在 | 新增用例 |
|------|:------:|:----:|:--------:|
| `council/validators.py` | 25.6% | **95.0%** | 16 |
| `plugins/manager.py` | 30.2% | **96.9%** | 13 |
| `llm/providers/ollama.py` | 30.5% | **98.3%** | 10 |

**覆盖内容**：

* **council/validators**：`_strip_extra_fields` 白名单清洗（含嵌套 `directed_response`）、
  `OutputGate` 三档门禁（BASIC/STANDARD/STRICT）、`validate_role_output`（越界字段剥离/必填校验）、
  `validate_json_output`（非法 JSON / 非对象拒绝）。
  顺带**清理死代码**：`key_arguments` 分支里一行无副作用的 set 字面量 + 未使用的循环变量。
* **plugins/manager**：`discover`（含非法 manifest → PluginError）、`load`（未知/缺入口/缺 `Plugin` 类/实例缓存）、
  `activate`（本地依赖优先激活 / 缺本地依赖 / 缺 pip 依赖 → 可操作错误）、`deactivate`（反向依赖保护）、
  `list/active/is_active`。
* **ollama provider**：`generate`（正常解析 token / HTTP 4xx-5xx / ConnectError 可操作提示 / ReadTimeout 提示）、
  `stream`（分块/跳过非法行/错误状态）、`health`（200 vs 5xx vs 异常）、客户端生命周期（复用/关闭/幂等）。

**覆盖率变化**：全仓 **74.8% → 75.6%**；`<35%` 的较大模块由 **18 → 15**。

---

## 12. 第三批：openai_compat + mcp/client（体量最大的两块）

| 模块 | 修复前 | 现在 | 新增用例 |
|------|:------:|:----:|:--------:|
| `llm/providers/openai_compat.py` | 20.5% | **87.2%** | 26 |
| `mcp/client.py` | 22.0% | **92.5%** | 19 |

**覆盖内容**：

* **openai_compat**：`_is_retryable`（可重试状态码/消息模式/不可重试码）、`_backoff_delay`（指数增长+封顶）、
  `_headers`/`_body` 构造（system 消息 / `model_override` / `stop` / stream）、
  `generate`（成功解析 token / 不可重试立即失败 / **可重试后成功** / 重试耗尽 / 连接失败 / 畸形载荷）、
  `stream`（SSE 增量拼接 / 错误状态）、`health`、连接池生命周期、`max_retries` 下限。
  —— 全程 `MockTransport`，退避延迟被置零，**无网络、无真实等待**。
* **mcp/client**：`initialize`（成功 / 携带 auth token / 错误响应）、6 个方法的**未初始化守卫**、
  `list_tools`/`call_tool`/`resources`/`prompts` 正常与错误路径、`shutdown`、
  协议异常（空响应 / 非预期响应类型）、`MCPClient` 连接注册、
  **初始化失败必须回收 transport（防子进程泄漏）**、未知断开 no-op、`list_all_tools`/`call_tool_from_server`。

**覆盖率变化**：全仓 **75.6% → 76.8%**；`<35%` 的较大模块由 **15 → 13**。

---

## 13. 第四批：council 上下文工具 + 渠道格式化

| 模块 | 修复前 | 现在 | 新增用例 |
|------|:------:|:----:|:--------:|
| `council/summary_extractor.py` | 7.7% | **100%** | 26（含 dispute_matrix/consensus_map） |
| `council/dispute_matrix.py` | 22.5% | **97.5%** | 同上 |
| `council/consensus_map.py` | 27.9% | **100%** | 同上 |
| `channels/formatter.py` | 29.6% | **100%** | 26 |

### 13.1 本批修复的 4 个真实缺陷（均在 `channels/formatter.py`）

| # | 缺陷 | 现象 | 修复 |
|---|------|------|------|
| **D-9** | Telegram 转义**顺序错误** | `a < b` → `a &amp;lt; b`（**二次转义**，渲染成字面量 `&lt;`） | 先转义 `&` 再转 `<`/`>` |
| **D-10** | `truncate` **超出上限** | `truncate("abcdef", 2)` → `'abcde...'`（8 字符 > 2；切片变负） | `max_length <= len(suffix)` 时硬截断；负值返回 "" |
| **D-11** | 空列表产生**孤立符号** | `format_list([])` → `'\n• '` | 空列表返回 "" |
| **D-12/14** | **围栏代码块被拆坏 / 语言标签丢失** | Telegram 的三反引号代码块被内联规则拆成 `<code>`+`python…`；Discord/Slack 丢失语言标签 `python` | 围栏规则**先于**内联规则；用 lambda 保留语言标签 |
| **D-13** | Slack **粗体变斜体** | `**b**` → `_b_`（`**` 规则产物被 `*` 规则二次改写） | 粗体先占位、斜体转换后再还原 |

### 13.2 覆盖率变化

全仓 **76.8% → 77.6%**；`<40%` 的较大模块由 **18 → 14**。

---

## 14. 第五批：deepseek / linux_sandbox / mcp-transport

| 模块 | 修复前 | 现在 | 新增用例 |
|------|:------:|:----:|:--------:|
| `llm/providers/deepseek.py` | 31.3% | **98.5%** | 12（+1 ollama 回归） |
| `sandbox/linux_sandbox.py` | 28.4% | **88.9%** | 12 |
| `mcp/transport.py` | 34.2% | **77.4%** | 14 |

### 14.1 本批修复：D-15 —— `model_override` 被静默忽略

**发现**：`OllamaProvider` 与 `DeepSeekProvider` 在 `generate`/`stream` 中都写死
`"model": self.model`，**完全忽略 `request.model_override`**；而 `OpenAICompatProvider`
是 `request.model_override or self.model`。

**影响**：任务级模型绑定 / 运行时状态切换对 ollama、deepseek **静默失效**——
调用方以为切了模型，实际仍用 provider 构造时的模型（与 D-2 同类"换了源却不说"）。

**修复**：统一为 `request.model_override or self.model`（4 处），实测 payload 正确带出覆盖模型。

### 14.2 覆盖要点

* **deepseek**：`_build_messages`、`generate`（success/reasoning_content/**model_override**/
  enable_thinking/默认 4096/ConnectError/ReadTimeout/HTTP 4xx）、`stream`（SSE 增量、
  `[DONE]` 跳过、畸形行忽略、model_override）、`health`、连接池生命周期。
* **linux_sandbox**：平台探测、工厂分派（Linux/非 Linux）、能力检测（unshare/cgroup）、
  非 Linux 回退执行、**模拟 Linux 的 unshare 包装命令构造**（含 `--net` 开关）、
  超时（`linux hardened`）、cgroup 限额写入 / 残留进程 kill。
* **mcp/transport**：`_StdoutProtocol` 连接事件、HTTP（aiohttp 缺失优雅降级 /
  未连接报错 / `receive` 不支持 / 请求体构造 / 不可解析报文忽略 / 通知转发）、
  SSE（降级 / 事件队列）、Process（真实 `cat` 往返 / 未启动安全）、工厂函数。

### 14.3 覆盖率变化

全仓 **77.6% → 78.3%**；`<40%` 的较大模块由 **14 → 11**。

---

## 15. 第六批：三个 API 路由（requirements / mcp / llm）

| 模块 | 修复前 | 现在 | 新增用例 |
|------|:------:|:----:|:--------:|
| `api/routers/requirements.py` | 24.7% | **79.8%** | 14 |
| `api/routers/mcp.py` | 35.0% | **88.3%** | 10 |
| `api/routers/llm.py` | 36.6% | **98.6%** | 15 |

### 15.1 本批修复：D-16 —— 导出接口默认参数不可用

`GET /requirements/export/{doc_id}` 的签名是 `format: str = "markdown"`，
但实现只处理 `json` 与 `csv`，其余走 `else → {"status":"failed","error":"Unsupported format"}`
—— 即**用默认参数调用必然失败**。

**修复**：新增 markdown 分支（重建 `# 标题` + `- [ ] 条目`），默认调用现在可用。

### 15.2 覆盖要点

* **requirements**：parse（空内容/成功/长描述截断）、import（空内容/建单/`auto_start` 契约）、
  templates、validate（缺标题/缺条目/合法文档）、export（**默认 markdown**/json/csv/不支持格式）。
* **mcp**：servers 列表、connect/filesystem（已连接/错误）、call_tool（成功/错误）、
  list_server_tools（未连接/成功/异常）、disconnect（成功/异常）—— 全程假 client，无 npx。
* **llm**：health/state/usage/providers/history/reasoning（含 check 与 config 更新）/
  aliases（列表 + resolve 404）/routing（配置 + rollup + 400）/state update 全套校验（5 类 422）/
  state reset/routing 写操作（task binding、chain、delete）。

### 15.3 覆盖率变化

全仓 **78.3% → 79.1%**；`<40%` 的较大模块由 **11 → 8**。

---

## 16. 第七批：渠道适配器 + 请求签名

| 模块 | 修复前 | 现在 | 备注 |
|------|:------:|:----:|------|
| `channels/webhook_adapter.py` | 34.7% | **74.4%** | 含签名/统计/健康检查 |
| `channels/qq_adapter.py` | 27.0% | **41.0%** | |
| `channels/telegram_adapter.py` | 28.2% | **42.3%** | |
| `channels/wechat_adapter.py` | 31.1% | **53.4%** | 含 SHA1 签名校验 |
| `channels/discord_adapter.py` | 32.0% | **54.0%** | |
| `security/signing.py` | 38.8% | **100%** | 8 用例 |

### 16.1 本批修复：D-17 —— 渠道适配器**无法用真实配置构造**

**发现**：`ChannelAdapter.__init__` 对 dict 配置直接 `ChannelConfig(**config)`，
而 5 个适配器都会传入平台专有键（`url` / `bot_token` / `port` / `corp_id` …）：

```
WebhookAdapter({"channel_type": WEBHOOK, "url": "http://x"})
  → TypeError: ChannelConfig.__init__() got an unexpected keyword argument 'url'
```

若改把配置塞进 `extra`，适配器又读的是**顶层 dict**（`config.get("url")`）→ 拿到空值。
**后果：所有渠道适配器要么构造崩溃、要么平台参数全为默认值 —— 渠道功能实质不可用。**

**修复**：`ChannelAdapter.__init__` 把专有键归入 `config.extra`、一等字段照常构造，
并保留 `raw_config` 供适配器读取自身键。实测 `url`/`secret` 正确生效、`extra` 可追溯。

### 16.2 覆盖要点

* **webhook**：start/stop、HMAC-SHA256 签名（确定性与无密钥空串）、发送成功/失败/异常、
  `X-Signature` 头、`send_message_to_user` 的 direct 元数据、健康检查三态（200/503/无 URL）。
* **wechat**：`verify_signature`（正确/错误/无 token 放行）。
* **qq**：`send_message` 按 `group_` / `user_` 前缀路由。
* **telegram / discord**：`send_message` 经 `_call_api` 的请求构造。
* **signing**：签名往返、篡改/过期/未来/重放四类拒绝、`sign_dict`、nonce 上限裁剪。

### 16.3 覆盖率变化

全仓 **79.1% → 79.8%**；`<40%` 的较大模块由 **8 → 2**（仅剩 `deployments` 路由与 `hot_reload`）。

---

## 17. 结论

MoRE OS 现有代码**功能覆盖完整、工程化程度高**（49.6k 行 / 1588 测试 / 73.8% 覆盖 /
ruff 全通过 / 18 端点全通 / 多层可观测 + 治理 + 安全防护），综合 **7.6/10**。

主要短板集中在**正确性的量化**（交付成功率含历史样本、缺趋势）与
**覆盖率长尾**（13 个较大模块 <35%），另有 1 处**可观测误报**（A-1）应优先修复。

*执行人: Codex · 2026-10-05*
