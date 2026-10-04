# 快速上手（5 分钟）

## 1. 构建

```bash
python tools/build.py       # 提取内核 + 生成 dist/*.zip
python tools/verify.py      # 离线自检（不需要模型）
```

## 2. 配置模型

复用主仓约定（`.env` 或环境变量）：

```bash
export MORE_LMSTUDIO_ENDPOINT=http://localhost:1234/v1
export MORE_LMSTUDIO_MODEL=ornith-1.5-35b-a3b
export MORE_OLLAMA_ENDPOINT=http://localhost:11434   # 兜底层，强烈建议配置
export MORE_OLLAMA_MODEL=qwen2.5:7b
```

> 先跑 `code-shop preflight` —— 它会检查模型是否存在、兜底链是否完整。
> 配置错误（例如模型名写错、漏配兜底 provider）会在这里直接报出来。

## 3. 生成代码

```bash
code-shop generate -q "实现 Python 函数 luhn_check(card) 校验银行卡号，只输出代码"
```

输出包含四段信息：

```
状态      : success   闸门: 通过
控制器裁决: pass
  ✓ syntax       1 个代码块语法通过
  ✓ logic        27 行代码
  ✓ requirement  需求符号覆盖 1/1 = 100%
阶段耗时  : L4=0.1ms  L1=0.0ms  L0=7540.1ms
```

## 4. 查看指标与交付

```bash
code-shop metrics --window 3600
```

返回 `llm`（token / 延迟分位 / 成功率）与 `delivery`
（交付成功率 / 阻断原因分布 / 各层耗时 p50）。
