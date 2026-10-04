#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# more-rollout.sh — MoRE OS canary rollout CLI
#
# Stages (min dwell time):
#   T0 baseline  : stable=100 / canary=0
#   T1 1% canary : 99 / 1    (1 h min dwell)
#   T2 5% canary : 95 / 5    (4 h min dwell)
#   T3 50% half  : 50 / 50   (24 h min dwell)
#   T4 100% full : 0 / 100   (permanent)
#
# Usage:
#   more-rollout.sh status
#   more-rollout.sh start --stage t1          # enter T1 (from T0)
#   more-rollout.sh promote --to t[1234]      # jump stage manually
#   more-rollout.sh rollback --reason <STR>   # back to T0 (100:0) + monitor CLI rollback
#   more-rollout.sh finalize                  # T4 stable at 100% canary long-term:
#                                               disable more-core-stable.service;
#                                               rewrite weights 0/100 permanently
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NGINX_CONF="$DEPLOY_DIR/nginx/more_os_canary.conf"
MONITOR="$SCRIPT_DIR/canary_monitor.py"
PYTHON_BIN="${PYTHON_BIN:-python3}"

STAGE_FILE="/tmp/more-rollout.stage"
DWELL_FILE="/tmp/more-rollout.dwell-start"
STATE_DIR="/var/lib/more-rollout"

# ---------------------------------------------------------------------------
# Stage metadata (weights + min dwell seconds)
# Bash-3 compatible NO associate arrays (macOS default bash 3.2)
# ---------------------------------------------------------------------------
STAGE_NAMES="t0 t1 t2 t3 t4"
# ── Stable weights (upstream percent)
STABLE_W_t0=100; STABLE_W_t1=99;  STABLE_W_t2=95;  STABLE_W_t3=50;  STABLE_W_t4=0
# ── Canary weights (upstream percent)
CANARY_W_t0=0;   CANARY_W_t1=1;   CANARY_W_t2=5;   CANARY_W_t3=50;  CANARY_W_t4=100
# ── Min dwell seconds per stage
DWELL_S_t0=0;    DWELL_S_t1=3600; DWELL_S_t2=14400;DWELL_S_t3=86400;DWELL_S_t4=0

# ── Indirect lookup helpers (Bash-3 compatible, no declare -A) ────────────
stage_var()  { local v="$1_$2"; printf '%s' "${!v:-}"; }
valid_stage_or_die() {
    local s="$1"
    case "$s" in
        t0|t1|t2|t3|t4) : ;;
        *) die "invalid stage: $s (must be one of $STAGE_NAMES)" ;;
    esac
}

log()  { printf '\033[1;36m[more-rollout]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[more-rollout WARN]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[more-rollout ERR]\033[0m %s\n' "$*" >&2; exit 1; }

mkdir -p "$STATE_DIR" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Persisted state helpers
# ---------------------------------------------------------------------------
current_stage() {
    if [[ -f "$STAGE_FILE" ]]; then cat "$STAGE_FILE"; else echo "t0"; fi
}
set_stage() {
    local s="$1"
    valid_stage_or_die "$s"
    echo "$s" > "$STAGE_FILE"
    if [[ "$s" == "t0" || "$s" == "t4" ]]; then
        rm -f "$DWELL_FILE"
    else
        date +%s > "$DWELL_FILE"
    fi
}
dwell_elapsed_s() {
    [[ -f "$DWELL_FILE" ]] || { echo 0; return; }
    local start now
    start="$(cat "$DWELL_FILE")"
    now="$(date +%s)"
    echo $(( now - start ))
}
dwell_remaining_s() {
    local stage="$1" req el rem
    req="$(stage_var DWELL_S "$stage")"
    [[ -z "$req" ]] && req=0
    el="$(dwell_elapsed_s)"
    rem=$(( req - el ))
    (( rem < 0 )) && rem=0
    echo "$rem"
}

# ---------------------------------------------------------------------------
# nginx weight rewrite
# ---------------------------------------------------------------------------
rewrite_weights_and_reload() {
    local stable_w="$1" canary_w="$2"
    [[ -f "$NGINX_CONF" ]] || die "nginx conf not found: $NGINX_CONF"

    # use python for robust regex rewrite (same tokens as canary_monitor.py)
    "$PYTHON_BIN" - "$NGINX_CONF" "$stable_w" "$canary_w" <<'PY' || die "nginx weight rewrite failed"
import re, sys
path, stable_w, canary_w = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
pat = re.compile(r"server\s+127\.0\.0\.1:(?P<port>8765|8766)\s+weight=(?P<w>\d+)")
text = open(path).read()
def sub(m):
    port = m.group("port")
    new = stable_w if port == "8765" else canary_w
    return f"server 127.0.0.1:{port} weight={new}"
new_text, n = pat.subn(sub, text)
if n < 2:
    print(f"ERROR substituted {n} weight lines (<2)", file=sys.stderr)
    sys.exit(1)
open(path, "w").write(new_text)
PY

    log "nginx -t"
    nginx -t || die "nginx -t failed; abort reload"
    log "nginx -s reload"
    if command -v sudo >/dev/null 2>&1; then
        sudo -n nginx -s reload 2>/dev/null || nginx -s reload || die "nginx -s reload failed"
    else
        nginx -s reload || die "nginx -s reload failed"
    fi
}

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
cmd_status() {
    local stage sw cw rem el req
    stage="$(current_stage)"
    valid_stage_or_die "$stage"
    sw="$(stage_var STABLE_W "$stage")"; cw="$(stage_var CANARY_W "$stage")"
    rem="$(dwell_remaining_s "$stage")"
    el="$(dwell_elapsed_s)"
    req="$(stage_var DWELL_S "$stage")"

    printf "STAGE: %s (stable=%d%% / canary=%d%%)\n" "$stage" "$sw" "$cw"
    if [[ "$stage" == "t1" || "$stage" == "t2" || "$stage" == "t3" ]]; then
        printf "DWELL: elapsed %ss of %ss required  →  %ss remaining\n" \
               "$el" "$req" "$rem"
    fi

    # monitor window status (if running)
    if [[ -x "$MONITOR" || -r "$MONITOR" ]]; then
        local mon_out
        if mon_out="$("$PYTHON_BIN" "$MONITOR" --status 2>/dev/null)"; then
            printf "MONITOR: %s\n" "$mon_out"
        else
            warn "canary_monitor --status failed (monitor service not running?)"
        fi
    fi

    # auto-promote: if dwell reached + no red lights → print promotion hint
    if [[ "$stage" == "t1" || "$stage" == "t2" || "$stage" == "t3" ]]; then
        local next=""
        case "$stage" in
            t1) next="t2" ;;
            t2) next="t3" ;;
            t3) next="t4" ;;
        esac
        if (( rem == 0 )); then
            log "dwell complete → can auto promote to $next now with: $0 promote --to $next"
        else
            log "next auto-promote to $next in: ${rem}s (min dwell not yet reached)"
        fi
    fi
}

cmd_start() {
    local stage cur sw cw
    stage="$1"
    case "$stage" in
        t1|t2|t3|t4) valid_stage_or_die "$stage" ;;
        *) die "start --stage must be one of: t1 t2 t3 t4" ;;
    esac
    cur="$(current_stage)"
    [[ "$cur" == "t0" ]] || warn "start called but stage != t0 (cur=$cur); continuing anyway"

    sw="$(stage_var STABLE_W "$stage")"; cw="$(stage_var CANARY_W "$stage")"
    log "START stage=$stage → stable=$sw%% canary=$cw%%"
    rewrite_weights_and_reload "$sw" "$cw"
    set_stage "$stage"
    log "OK. Now monitor status with: $0 status"
}

cmd_promote() {
    local target cur order cur_i tgt_i i sw cw
    target="$1"
    cur="$(current_stage)"
    order="t0 t1 t2 t3 t4"
    cur_i=-1; tgt_i=-1; i=0
    for s in $order; do
        [[ "$s" == "$cur"    ]] && cur_i=$i
        [[ "$s" == "$target" ]] && tgt_i=$i
        i=$(( i + 1 ))
    done
    (( tgt_i < 0 )) && die "unknown --to target: $target"
    (( tgt_i <= cur_i )) && warn "promote target '$target' is not forward of cur '$cur'; treating as force-set"

    sw="$(stage_var STABLE_W "$target")"; cw="$(stage_var CANARY_W "$target")"
    log "PROMOTE cur=$cur → target=$target  (stable=$sw%% canary=$cw%%)"
    rewrite_weights_and_reload "$sw" "$cw"
    set_stage "$target"
    cmd_status
}

cmd_rollback() {
    local reason="${1:-unspecified}" sw cw
    warn "ROLLBACK to T0 (100%% stable / 0%% canary) — reason: $reason"
    sw="$(stage_var STABLE_W t0)"; cw="$(stage_var CANARY_W t0)"
    rewrite_weights_and_reload "$sw" "$cw"
    set_stage "t0"

    # notify monitor (fire rollback CLI path → disables self)
    if [[ -r "$MONITOR" ]]; then
        "$PYTHON_BIN" "$MONITOR" --force-rollback "more-rollout rollback: $reason" \
            2>/dev/null || true
    fi
    log "Rollback complete. Status:"
    cmd_status
}

cmd_finalize() {
    local cur="$(current_stage)"
    [[ "$cur" == "t4" ]] || die "finalize only allowed from stage t4 (100% canary stable ≥72h). cur=$cur"
    log "FINALIZE canary → long-term stable: disabling more-core-stable.service"
    rewrite_weights_and_reload 0 100
    if command -v systemctl >/dev/null 2>&1; then
        (systemctl stop more-core-stable &&
         systemctl disable more-core-stable) 2>&1 | while IFS= read -r line; do log "systemd: $line"; done || \
             warn "could not systemctl disable more-core-stable (run manually as root)"
    else
        warn "systemctl not available; please disable more-core-stable manually"
    fi
    log "Done. Canary (127.0.0.1:8766) is now the sole production backend."
}

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------
usage() {
    sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -eq 0 ]] && usage

cmd="$1"; shift
case "$cmd" in
    status)                           cmd_status ;;
    start)
        [[ "${1:-}" == "--stage" ]] || die "start needs: --stage t1|t2|t3|t4"
        cmd_start "${2:?missing stage arg}" ;;
    promote)
        [[ "${1:-}" == "--to" ]] || die "promote needs: --to t1|t2|t3|t4"
        cmd_promote "${2:?missing target arg}" ;;
    rollback)
        reason=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --reason) reason="${2:-unspecified}"; shift 2 ;;
                *) shift ;;
            esac
        done
        cmd_rollback "$reason" ;;
    finalize)                         cmd_finalize ;;
    *) usage ;;
esac
