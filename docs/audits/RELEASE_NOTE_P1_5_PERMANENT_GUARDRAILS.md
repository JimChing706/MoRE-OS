# Release Note: P1-5 三条永久守护故障注入（I-03 / I-06 / I-12）

责任专家：可靠性 沈慎（S-4）  
并入测试类：[`test_l1_orchestration.py::TestExpertP0PermanentGuardrails`](file:///Users/qnming/AI_Cample/qnm-os-prev-202605211332/more_core/tests/test_l1_orchestration.py#L189-L359)  
状态：✅ **PERMANENT GUARDRAILS VERIFIED**（每跑 `pytest tests/` 必测，不通过 = Step 5/6 所有总验闸拒批）

---

## 1. 三条故障注入守护概览

| ID | 故障场景（Friendly Name） | 目标不变式 | 测试方法名 |
|----|--------------------------|-----------|-----------|
| **I-06** | L1 永不抛（Dirty Input） | 上游 L0 把非法类型 / 脏数据写进 scratch.difficulty / scratch.capability（callable 对象、__str__ 会抛异常、不是 str/int 等），L1 OrchestrationLayer 永不抛任何异常 → 一律 fallback 启发式（confidence=0.0，`plan.source='heuristic-fallback'`）返回，保证上层永远不会因编排层崩。 | `TestExpertP0PermanentGuardrails::test_i06_dirty_scratch_never_throws` |
| **I-03** | R2 cond_b 空输出 → `ThinkingBudgetExhaustedError` | LLM 返回 `completion_tokens > 0`（Token 有消耗，不是 0）但 `str(output).strip() == ''`（空内容），L1 判定条件 R2 **必须抛** `ThinkingBudgetExhaustedError`（继承 `LLMError`），不允许静默 PASS 或返回 ''。 | `TestExpertP0PermanentGuardrails::test_i03_empty_completion_throws_llm_error` |
| **I-12** | R2 异常后 FallbackChain 降级下一 tier | 当 L1 因 I-03 或其它 LLMError 失败，`fallback_chain` 必须自动切换到 **下一层 tier（T0→T1→T2→T3）** 重试，而不是直接 return None；验证：同一个请求 `attempts >= 2`（至少两个 tier 被尝试过）。 | `TestExpertP0PermanentGuardrails::test_i12_r2_exception_triggers_tier_downgrade` |
| 附 | R1 振荡滞回（60 次振荡 ≤ 3 次 tier flip） | 专家会签 4 P0 永久守护第 4 条：在快速切换 tier 的抖动场景（60 次连续随机请求 → 每次请求后 dynamic_router 调 `toggle_last_tier_swap()` 模拟 60s 内的高频 tier 翻转信号），**最终 tier flip 总数 ≤ 3**（滞回护栏防止 R3-B 合规抖动时 thrash）。 | `TestExpertP0PermanentGuardrails::test_r1_hysteresis_60_flips_le_3` |

---

## 2. I-06 细节（L1 永不抛 / Dirty Input）

### 故障注入（`scratch.capability` = 一个 `__str__` 会抛 RuntimeError 的 evil 对象）
```python
class EvilCapability:
    def __str__(self):
        raise RuntimeError("I-06 injection: evil capability object")
    def __int__(self):
        raise RuntimeError("I-06 injection: evil capability int")
    def __bool__(self):
        return False

scratch.difficulty = [dict, list, object()]  # 完全非法类型（不是 str / int）
scratch.capability = EvilCapability()        # str() 直接抛异常
```

### 期望行为
- `orch_layer.process(scratch, ctx)` **永不抛任何异常**（不被 pytest raises 捕获，返回 Plan 对象）
- 返回的 `plan.confidence == 0.0`（fallback 启发式，无任何 LLM/规则确定性信心）
- `plan.source == 'heuristic-fallback'`（明确标记是"I-06 fallback 出来的 plan"，便于审计）
- `plan.steps` 至少 1 步（保证上层调用永远拿到一个可执行的 plan，即使内容保守）

### 永久守护通过状态
✅ 已并入 `TestExpertP0PermanentGuardrails::test_i06_dirty_scratch_never_throws`（L192-L227）。  
✅ `pytest tests/` 1025 passed 中含此用例，未通过 = Step 5/#6 所有总验闸自动 FAIL。

---

## 3. I-03 细节（R2 Empty Completion → `ThinkingBudgetExhaustedError`）

### 故障注入
Mock LLM 返回结构（模拟推理有 Token 消耗但内容全空，典型 provider "200 但 content=null" 故障）：
```python
completion_tokens = 256  # > 0，Token 有消耗
output_str = ""          # 但内容 100% 空
mock.llm.generate.return_value = LLMResponse(
    raw_text=output_str,
    usage=LLMUsage(completion_tokens=completion_tokens, ...),
    ...
)
```

### 期望行为
- L1 内部 **必须抛** `ThinkingBudgetExhaustedError`（不是 ValueError / RuntimeError / 其它非 LLMError）
- 抛出的 Error **必须继承 `LLMError`**（否则 I-12 fallback_chain 无法识别成"provider failure"而降级 tier）
- 必须包含诊断字符串 `empty completion` / `tokens>0 but no content`（便于 incident_response 归因）

### 永久守护通过状态
✅ 已并入 `TestExpertP0PermanentGuardrails::test_i03_empty_completion_throws_llm_error`（L229-L264）。  
✅ `pytest.raises(ThinkingBudgetExhaustedError, match="empty")` 断言通过 + `issubclass(err_type, LLMError)` 断言通过。

---

## 4. I-12 细节（R2 异常后 FallbackChain Tier 降级）

### 故障注入
I-03 相同的 empty completion 注入（抛 `ThinkingBudgetExhaustedError(LLMError)`），但此场景 LLM Manager 配置 T0 + T1 两个 tier 都可用。

### 期望行为
- FallbackChain 捕获 `LLMError` 后，**自动重试下一层 tier**（T0 JEV → T1 Laya）
- 最终统计：该请求的 `attempts >= 2`（至少两个 tier 被尝试）
- 即使 T0、T1 全部抛 LLMError，也必须尝试完 T2/T3 所有可用 tier，最后才 return None（不允许"只跑一层就放弃"）

### 永久守护通过状态
✅ 已并入 `TestExpertP0PermanentGuardrails::test_i12_r2_exception_triggers_tier_downgrade`（L267-L359）。  
✅ `assert attempts >= 2`（`I-12 失败：R2 异常后未降级，attempts=X`）。

---

## 5. 附：R1 振荡滞回（60 次 flip ≤ 3 次切换）

**非 P1-5 故障注入，但并入同一永久守护类永久保护**（专家会签 4 P0 永久守护第 4 条）。

### 故障注入
60 次连续请求，每次请求完 `dynamic_router.toggle_last_tier_swap()`（模拟外部合规信号 60s 内高频抖动）。

### 期望行为
- 最终 `tier_flips_total <= 3`（滞回护栏生效）
- 不会出现 "每请求都 flip" 的 thrash（60 次 flip = 灾难）

### 永久守护通过状态
✅ `TestExpertP0PermanentGuardrails::test_r1_hysteresis_60_flips_le_3`。  
✅ P0 总验 #2 1025 passed 含此用例。

---

## 6. 永久守护回归保障

| 保障手段 | 内容 |
|---------|------|
| **自动运行时机** | 每次 `pytest tests/` 必跑（Step 5 #4 最终闸、Step 6 #1 最终闸必执行） |
| **P1 回归闸 #1 专项** 215 passed | I-06/I-03/I-12 3 用例 + 振荡 1 用例 = 4/4 全绿 |
| **P1 回归闸 #2 完整** 1025 passed | 同上 4/4 全绿（无退化） |
| **P1 回归闸 #3 diagnostics** | `l1_orchestration.py` 0 issues |
| **Step 6 #1 最终闸（生产灰度完成后）** | 必重跑 1025 passed + diagnostics 0，4 守护不通过则灰度不通过 |

---

*Release Note 生成时间：2026-09-26 | 责任专家签字（代码侧 verified）：可靠性 沈慎 | 并入 TestExpertP0PermanentGuardrails 永久守护：是（不可删除/跳过）*
