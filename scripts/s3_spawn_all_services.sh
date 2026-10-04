#!/bin/bash
# S3 修复版：调用 /tmp/more_os_full_boot.sh（含 keepalive 长驻，对抗 TRAE Sandbox 进程回收）
# G-2-6 合规：0 侵入 more_core/**/*.py
ROOT=/Users/qnming/AI_Cample/qnm-os-prev-202605211332
LOG_WD="$ROOT/logs"
mkdir -p "$LOG_WD"
export ROOT
chmod +x /tmp/more_os_full_boot.sh 2>/dev/null || true
: > /tmp/_more_os_pids.txt

TS=$(date +%Y%m%d_%H%M%S)
BOOT_LOG="${LOG_WD}/more_os_full_boot_${TS}.log"
echo "[S3] boot at ${TS} using /tmp/more_os_full_boot.sh" > "${BOOT_LOG}"

bash -n /tmp/more_os_full_boot.sh || { echo "syntax fail in /tmp/more_os_full_boot.sh"; exit 1; }

# KeepAlive: 用父 shell 后台执行 full_boot.sh，本脚本负责 poll 直到服务启动
(
  set +u
  bash /tmp/more_os_full_boot.sh >> "${BOOT_LOG}" 2>&1
) &
MAIN_PID=$!
disown -h "${MAIN_PID}" 2>/dev/null || disown "${MAIN_PID}" 2>/dev/null || true
echo "[S3] full_boot MAIN_PID=${MAIN_PID}  log=${BOOT_LOG}"
echo "S0-FullBoot=${MAIN_PID}" >> /tmp/_more_os_pids.txt

MAX_WAIT=45
PORTS=(8011 8765 9988 9400 19090)
NAMES=(Core-8011 Stable-8765 Chassis-9988 Exporter-9400 Prom-19090)
echo "[S3] polling up to ${MAX_WAIT}s for 5 ports LISTEN ..."
step=1
allup=0
while [ "$step" -le "$MAX_WAIT" ]; do
  sleep 1
  allup=1
  for p in "${PORTS[@]}"; do
    if ! lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
      allup=0
      break
    fi
  done
  if [ "$allup" = "1" ]; then
    break
  fi
  step=$((step+1))
done

echo ""
echo "=== PIDs file ==="
cat /tmp/_more_os_pids.txt 2>/dev/null
echo ""
echo "=== Port status after ${step}s poll ==="
for i in "${!PORTS[@]}"; do
  p="${PORTS[$i]}"
  n="${NAMES[$i]}"
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    pid=$(lsof -nP -iTCP:"$p" -sTCP:LISTEN -Fp 2>/dev/null | head -1 | tr -d p)
    printf "  ✅ %-18s  LISTEN  pid=%-7s  port=%s\n" "$n" "$pid" "$p"
  else
    printf "  ❌ %-18s  NOT LISTEN  port=%s\n" "$n" "$p"
  fi
done
echo ""
echo "=== boot log tail (last 40 lines) ==="
tail -40 "${BOOT_LOG}" 2>/dev/null

