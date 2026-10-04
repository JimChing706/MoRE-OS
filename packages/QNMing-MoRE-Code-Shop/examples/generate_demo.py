#!/usr/bin/env python3
"""示例：用 Code Shop 门面生成代码并打印完整结论。

    python examples/generate_demo.py "实现 Python 函数 is_palindrome(s)"
"""

from __future__ import annotations

import asyncio
import json
import sys

from qnming_code_shop.facade import generate_code


async def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "实现 Python 函数 is_palindrome(s) 判断回文"
    result = await generate_code(query, actor="example")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2)[:1500])
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
