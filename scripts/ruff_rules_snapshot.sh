#!/usr/bin/env bash
# 导出 ruff 当前解析出的启用规则集（规则集漂移守卫）。
#
# 背景（D-20 / RR-8）：MoRE OS 收编 ruff 0.16.10 的**默认规则集**（413 条）。
# 该集合由 ruff 版本决定 —— 升级 ruff 或改动 select/ignore 都会让门禁口径静默漂移。
# 本脚本把它固化成基线文件，CI 逐步比对，漂移即失败。
#
# 用法：
#   ./scripts/ruff_rules_snapshot.sh            # 打印当前规则集
#   ./scripts/ruff_rules_snapshot.sh --check    # 与基线比对（CI 用）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INNER="$ROOT/more_core"
BASELINE="$ROOT/.ruff-rule-set-baseline.txt"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

[[ -x "$PYTHON" ]] || { echo "✗ 找不到 python: $PYTHON（可用 PYTHON=... 覆盖）" >&2; exit 1; }

# --isolated：忽略项目配置里的 select/ignore，取 ruff 自身的默认集。
snapshot() {
  (cd "$INNER" && "$PYTHON" -m ruff check --isolated --show-settings more_core/version.py) \
    | sed -n '/linter.rules.enabled/,/^]/p' \
    | grep -oE '\([A-Z]+[0-9]+\)' | tr -d '()' | sort -u
}

CUR="$(snapshot)"
COUNT="$(printf '%s\n' "$CUR" | grep -c . || true)"
[[ "$COUNT" -ge 300 ]] || { echo "✗ 规则集解析异常（仅 $COUNT 条），拒绝比对" >&2; exit 1; }

if [[ "${1:-}" == "--check" ]]; then
  if diff -u "$BASELINE" <(printf '%s\n' "$CUR"); then
    echo "✓ ruff 规则集与基线一致（$COUNT 条）"
  else
    echo "✗ ruff 规则集已漂移：请复核新规则影响面后更新基线" >&2
    exit 1
  fi
else
  printf '%s\n' "$CUR"
fi
