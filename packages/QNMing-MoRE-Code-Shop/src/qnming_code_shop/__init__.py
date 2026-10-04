"""QNMing MoRE Code Shop — 代码生成能力的产品化封装。

本包把 MoRE OS 内核中**已验证**的代码生成链路提取为独立可分发的产品：

    需求输入 → LLM 生成 → 多维校验（语法/逻辑/需求匹配）
             → 沙箱验证 → 交付台账 + 运行指标

其中 ``more_core`` 为内核的**自包含拷贝**（保留内部相对导入，不做改写），
``qnming_code_shop`` 为产品层（CLI / 门面 API / 构建信息）。
"""

from __future__ import annotations

__all__ = ["__version__", "PRODUCT_NAME", "PRODUCT_TAGLINE"]

__version__ = "0.1.0"
PRODUCT_NAME = "QNMing-MoRE-Code-Shop"
PRODUCT_TAGLINE = "可验证、可追溯的代码生成流水线"
