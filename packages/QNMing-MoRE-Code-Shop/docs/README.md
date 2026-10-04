# QNMing-MoRE-Code-Shop — 文档

沿用主仓（MoRE OS）的文档约定：**顶层只放当前生效的规范/手册**，
过程性材料（审计/评估/验证）统一放在主仓 `docs/audits/`，本包不重复复制。

| 文档 | 说明 |
|------|------|
| [QUICKSTART.md](QUICKSTART.md) | 5 分钟跑通：预检 → 生成 → 查看指标 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 生成链路与三大保障（正确性/可信度/可观测） |
| 主仓 `docs/audits/` | 审计、RCA、阶段评估、加固批次记录 |

## 可追溯性

本包由 `tools/build.py` 生成，构建时写入 `src/qnming_code_shop/_build_info.py`：

```python
SOURCE_COMMIT = "<主仓提交短哈希>"
BUILD_TIME    = "<构建时间>"
VENDORED_FILES = <提取文件数>
```

据此可定位任一分发包对应的主仓版本。
