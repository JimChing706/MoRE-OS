#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install_canary.sh — Install MoRE OS canary systemd services + nginx conf.
#
# Run as root (or sudo). Will:
#   1. Copy 4 systemd unit files → /etc/systemd/system/ (with placeholders
#      replaced via env variables below).
#   2. Chmod +x scripts under deploy/canary/scripts.
#   3. Symlink nginx/more_os_canary.conf → /etc/nginx/conf.d/ or
#      /usr/local/etc/nginx/conf.d/.
#   4. systemctl daemon-reload + enable 4 services.
#   5. nginx -t (only, does not reload — run `more-rollout.sh start --stage t1`).
#
# Required env variables (all are resolved interactively if unset):
#   MORE_CORE_ROOT   MoRE OS project root (has more_core/ + bailongma_chassis/)
#   PYTHON_BIN       python3 interpreter path with more_core venv activated
#   SERVICE_USER     systemd service user (non-root, e.g. more)
#   SERVICE_GROUP    systemd service group (e.g. more)
#   SERVER_NAME      nginx server_name (e.g. more-os.example.com or default)
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$DEPLOY_DIR/../.." && pwd)"

log()  { printf '\033[1;36m[install-canary]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[install-canary ERR]\033[0m %s\n' "$*" >&2; exit 1; }

# require root
if [[ "$(id -u)" -ne 0 ]]; then
    die "please run as root (sudo ./install_canary.sh)"
fi

# resolve vars (interactive if unset)
if [[ -z "${MORE_CORE_ROOT:-}" ]]; then
    MORE_CORE_ROOT="$PROJECT_ROOT"
    read -rp "MORE_CORE_ROOT [$MORE_CORE_ROOT]: " u; MORE_CORE_ROOT="${u:-$MORE_CORE_ROOT}"
fi
if [[ -z "${PYTHON_BIN:-}" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
    read -rp "PYTHON_BIN [$PYTHON_BIN]: " u; PYTHON_BIN="${u:-$PYTHON_BIN}"
fi
if [[ -z "${SERVICE_USER:-}" ]]; then
    SERVICE_USER=more
    read -rp "SERVICE_USER [$SERVICE_USER]: " u; SERVICE_USER="${u:-$SERVICE_USER}"
fi
if [[ -z "${SERVICE_GROUP:-}" ]]; then
    SERVICE_GROUP=more
    read -rp "SERVICE_GROUP [$SERVICE_GROUP]: " u; SERVICE_GROUP="${u:-$SERVICE_GROUP}"
fi
if [[ -z "${SERVER_NAME:-}" ]]; then
    SERVER_NAME=default_server
    read -rp "SERVER_NAME (nginx server_name, e.g. more-os.example.com or _) [$SERVER_NAME]: " u
    SERVER_NAME="${u:-$SERVER_NAME}"
fi

log "Config summary:"
log "  MORE_CORE_ROOT = $MORE_CORE_ROOT"
log "  PYTHON_BIN     = $PYTHON_BIN"
log "  SERVICE_USER   = $SERVICE_USER"
log "  SERVICE_GROUP  = $SERVICE_GROUP"
log "  SERVER_NAME    = $SERVER_NAME"
for var in MORE_CORE_ROOT PYTHON_BIN; do
    [[ -n "${!var}" ]] || die "$var is empty; please export it first"
done
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "PYTHON_BIN not executable: $PYTHON_BIN"
[[ -d "$MORE_CORE_ROOT/more_core" ]] || die "MORE_CORE_ROOT invalid (no more_core/ subdir): $MORE_CORE_ROOT"
[[ -f "$MORE_CORE_ROOT/bailongma_chassis/target/release/bailongma_chassis" ]] || \
    warn "bailongma_chassis release bin not found; build with: \
cd $MORE_CORE_ROOT/bailongma_chassis && cargo build --release"

# ensure service user exists
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    log "creating system user $SERVICE_USER"
    useradd -r -s /usr/sbin/nologin -d "$MORE_CORE_ROOT" "$SERVICE_USER"
fi

# chmod scripts
chmod +x "$SCRIPT_DIR/more-rollout.sh"
chmod +x "$SCRIPT_DIR/canary_monitor.py"

# placeholders + copy systemd units
SYSTEMD_DIR=/etc/systemd/system
SED_ARGS=(
    -e "s#__MORE_CORE_ROOT__#$MORE_CORE_ROOT#g"
    -e "s#__PYTHON_BIN__#$PYTHON_BIN#g"
    -e "s#__SERVICE_USER__#$SERVICE_USER#g"
    -e "s#__SERVICE_GROUP__#$SERVICE_GROUP#g"
)
for unit in more-core-stable more-core-canary blm-chassis canary-monitor; do
    src="$DEPLOY_DIR/systemd/$unit.service"
    dst="$SYSTEMD_DIR/$unit.service"
    [[ -f "$src" ]] || die "missing systemd unit source: $src"
    sed "${SED_ARGS[@]}" "$src" > "$dst"
    chmod 0644 "$dst"
    log "systemd → $dst"
done

# nginx conf placeholder replace + install
NGINX_CONF_SRC="$DEPLOY_DIR/nginx/more_os_canary.conf"
[[ -f "$NGINX_CONF_SRC" ]] || die "missing nginx conf source: $NGINX_CONF_SRC"
NGINX_DIR=""
for d in /etc/nginx/conf.d /usr/local/etc/nginx/conf.d; do
    if [[ -d "$(dirname "$d")" ]]; then mkdir -p "$d"; NGINX_DIR="$d"; break; fi
done
[[ -n "$NGINX_DIR" ]] || die "no nginx conf.d dir found (/etc/nginx nor /usr/local/etc/nginx)"

NGINX_CONF_DST="$NGINX_DIR/more_os_canary.conf"
NGINX_PORT_PLACEHOLDERS=(
    -e "s#__SERVER_NAME__#$SERVER_NAME#g"
    -e "s#__STABLE_WEIGHT__#100#g"
    -e "s#__CANARY_WEIGHT__#0#g"
)
sed "${NGINX_PORT_PLACEHOLDERS[@]}" "$NGINX_CONF_SRC" > "$NGINX_CONF_DST"
log "nginx   → $NGINX_CONF_DST (weights T0: stable=100 canary=0)"

# perms on data dir
DATA_DIR="$MORE_CORE_ROOT/more_core/more_core/data"
mkdir -p "$DATA_DIR"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$DATA_DIR" "$MORE_CORE_ROOT/deploy"

# enable services
systemctl daemon-reload
for svc in more-core-stable more-core-canary blm-chassis canary-monitor; do
    systemctl enable "$svc.service" 2>&1 | while IFS= read -r line; do log "systemd enable $svc: $line"; done
    log "enabled: $svc.service"
done

# syntax check only (don't reload/start user services automatically yet)
if command -v nginx >/dev/null 2>&1; then
    log "nginx -t check:"
    nginx -t 2>&1 | while IFS= read -r line; do log "nginx: $line"; done
fi

cat <<EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Install DONE ✅
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Next steps:
   1) Start services (T0 100% stable baseline):
        systemctl start more-core-stable blm-chassis
        # wait for stable baseline, then:
   2) Start canary + monitor:
        systemctl start more-core-canary canary-monitor
   3) Enter T1 (1% canary):
        $SCRIPT_DIR/more-rollout.sh start --stage t1
   4) Watch progress:
        $SCRIPT_DIR/more-rollout.sh status
        journalctl -fu canary-monitor
        journalctl -fu more-core-canary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF
