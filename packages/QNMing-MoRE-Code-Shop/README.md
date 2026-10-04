# QNMing-MoRE-Code-Shop

> **可验证、可追溯的代码生成流水线** · v0.1.0（初版）

本包从 **QNMing MoRE OS** 内核中提取**已验证**的代码生成链路，封装为可独立分发的产品：

```
需求输入 ──▶ LLM 生成 ──▶ 多维校验 ──▶ 沙箱验证 ──▶ 交付台账 ──▶ 运行指标
                          ├─ 语法（真实 parse/配平）
                          ├─ 逻辑（占位/空实现检测）
                          └─ 需求匹配度（符号覆盖）
```

## 为什么可信

| 能力 | 说明 |
|------|------|
| **产出正确性** | 交付前必经三维闸门；未过则拦截并记审计，绝不静默放行 |
| **交付可信度** | 每次交付写入台账：状态 / 权责 / 版本 / 工件 SHA256 / 裁决 / 阻断原因 |
| **可观测性** | LLM 四入口埋点（token + 延迟）+ 逐层阶段耗时，可查询可归因 |
| **安全边界** | 沙箱 AST 判定（反射式导入/eval 混淆可拦）、路径穿越拦截、危险环境变量净化 |

## 快速开始

```bash
# 1) 从主仓提取 + 打包（可重复执行）
python tools/build.py

# 2) 离线自检
python tools/verify.py

# 3) 安装并使用
pip install -e .
code-shop preflight                                  # LLM 链路预检
code-shop generate -q "实现 Python 函数 is_palindrome(s)"   # 生成 + 校验 + 记账
code-shop metrics                                    # token / 延迟 / 成功率
code-shop serve --port 8011                          # 起完整 API
```

## 目录结构

```
QNMing-MoRE-Code-Shop/
├── tools/build.py          # 提取内核源码 + 打包（唯一构建入口）
├── tools/verify.py         # 离线自检（不依赖外部模型）
├── src/more_core/          # ← 由 build.py 从主仓提取（勿手改）
├── src/qnming_code_shop/   # 产品层：门面 API + CLI
├── docs/                   # 文档索引与快速上手
├── examples/               # 可运行示例
└── dist/                   # 分发包（zip + sha256）
```

## 与主仓的关系

* 本包是**提取产物**：`src/more_core/` 由 `tools/build.py` 从主仓
  `more_core/more_core/` 复制而来，**不做包名改写**（保留 210 个模块的内部相对导入）。
* 主仓仍是唯一事实来源；升级流程 = 主仓改 → 跑测试 → `python tools/build.py`。
* 过程性材料（审计/评估）不复制，统一引用主仓 `docs/audits/`。

## 许可

Apache License 2.0，见 [LICENSE](LICENSE)。
