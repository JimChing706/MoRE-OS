#!/bin/bash
# S2 固件自检：密钥、数据库、CLI 入口
set +e
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
echo "=== S2 固件自检 ==="
echo "[S2-1] more_core/.env 关键密钥清单:"
REPO_ROOT_PY="${REPO_ROOT}" python3 <<'PYEOF'
from pathlib import Path
import os
keys = [
    "MORE_API_KEY", "MORE_BASE_URL", "MORE_REQUIRE_API_KEY",
    "MORE_DISABLE_TIER_0", "MORE_CHASSIS_URL",
    "OREO_API_KEY", "OREO_BASE_URL",
    "MODEL_ORCHESTRATOR_DEFAULT_PROVIDER",
]
ef = Path(os.environ["REPO_ROOT_PY"]) / "more_core" / ".env"
if ef.exists():
    data = {}
    for raw in ef.read_text().splitlines():
        if raw.startswith("#") or "=" not in raw:
            continue
        k, _, v = raw.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        data[k] = v
    for k in keys:
        if k in data and data[k]:
            print(f"     ✅ {k:<45s} len={len(data[k]):>4d}")
        elif k in data:
            print(f"     ⚠️  {k:<45s} 空值")
        else:
            print(f"     ❌ {k:<45s} 未设置")
else:
    print(f"     more_core/.env 不存在 (searched: {ef})")
PYEOF

echo ""
echo "[S2-2] 数据库完整性:"
for DBF in \
  "more_core/data/more_tasks.db" \
  "more_core/data/codegen_evolution.db" \
  "more_core/data/outputs.db" \
  "more_core/data/native_runs/provenance.db" \
  "more_core/data/provenance.db"; do
    FULL="$REPO_ROOT/$DBF"
    if [ -f "$FULL" ]; then
        SZ=$(python3 -c "import os; print(os.path.getsize('$FULL'))" 2>/dev/null || echo 0)
        if [ "$SZ" -gt 0 ]; then
            echo "     ✅ $DBF  size=${SZ}B"
        else
            echo "     ⚠️  $DBF  空文件"
        fi
    else
        echo "     ❌ $DBF  不存在 (首次启动可接受)"
    fi
done

echo ""
echo "[S2-3] 后端 CLI 入口 (more_core.cli):"
cd "${REPO_ROOT}/more_core" && python3 -m more_core.cli --help 2>&1 | head -12

echo ""
echo "[S2-4] Chassis 可用性:"
lsof -nP -iTCP:9988 -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{printf("     ✅ Chassis listen on 9988: pid=%s cmd=%s\n", $2, $1)}'
PID_9988=$(lsof -nP -iTCP:9988 -sTCP:LISTEN -Fp 2>/dev/null | head -1 | tr -d 'p')
if [ -n "${PID_9988}" ] && [ -d "/proc/${PID_9988}" ] 2>/dev/null; then true; fi
if [ -n "${PID_9988}" ]; then
  BIN=$(ps -p "${PID_9988}" -o comm= 2>/dev/null || echo "unknown")
  PPID=$(ps -p "${PID_9988}" -o ppid= 2>/dev/null || echo "?")
  echo "     ✅ PID=${PID_9988}  BIN=${BIN}  PPID=${PPID}"
fi
