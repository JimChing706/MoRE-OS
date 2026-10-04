#!/usr/bin/env python3
"""MoRE OS Canary Health Monitor — 5 red-light auto-rollback.

Samples every SAMPLE_INTERVAL seconds (default 10s), maintains a 3 minute
(180s) sliding window of metrics, and auto-rolls back nginx weights to
100% stable (0% canary) when ANY red light triggers *for the entire window*.

5 RED LIGHTS (all must be True for the FULL sliding window → rollback):
  R1  p95 /api/v1/a2a echo latency ≥ 2000 ms
  R2  evolution summary overall_pass_rate ≤ 25 %
  R3  chassis delegation failure rate ≥ 5 %
  R4  1h tier transitions (flip count) ≥ 3
  R5  /api/v1/health  ≠ HTTP 200  OR  status != "healthy"

On rollback we:
  1. Rewrite __NGINX_CONF__ weights to STABLE=100 / CANARY=0.
  2. Run `nginx -t && sudo -n nginx -s reload` (fail-safe).
  3. If SYSADMIN API key present → POST canary:/ops/tier_rollback (P1-4 G-2).
  4. syslog + stderr, then disable self (avoid flapping).

Run via systemd user service: canary-monitor.service
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shlex
import signal
import statistics
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque
from urllib import error as urlerr
from urllib import parse as urlparse
from urllib import request as urlrequest

# ---------------------------------------------------------------------------
# Config (override via env vars, see canary-monitor.service)
# ---------------------------------------------------------------------------
STABLE_BASE      = os.getenv("MORE_CANARY_MON_STABLE", "http://127.0.0.1:8765")
CANARY_BASE      = os.getenv("MORE_CANARY_MON_CANARY", "http://127.0.0.1:8766")
CHASSIS_BASE     = os.getenv("MORE_CANARY_MON_CHASSIS","http://127.0.0.1:9988")
NGINX_CONF       = Path(os.getenv("MORE_CANARY_MON_NGINX_CONF",
                                  "/opt/more-core/deploy/canary/nginx/more_os_canary.conf"))
SAMPLE_INTV_S    = int(os.getenv("MORE_CANARY_MON_SAMPLE_INTERVAL_SECONDS", "10"))
SLIDING_WINDOW_S = int(os.getenv("MORE_CANARY_MON_SLIDING_WINDOW_SECONDS",  "180"))
API_KEY_FILE     = Path(os.getenv("MORE_CANARY_MON_SYSADMIN_API_KEY_FILE",
                                  "/opt/more-core/more_core/.env"))

ECHO_TEXT    = "canary-monitor-health-echo-ping"
RED_P95_MS   = 2000.0
RED_PASS_PCT = 25.0
RED_DEL_FAIL = 0.05
RED_TIER_FLIP_1H = 3

# ---------------------------------------------------------------------------
log = logging.getLogger("canary_monitor")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@dataclass
class Sample:
    t: float
    # R1: echo latency ms (None = probe failed)
    echo_ms: float | None
    # R2: overall pass rate % (None = endpoint failed)
    pass_pct: float | None
    # R3: chassis delegation fail rate (None = unknown)
    del_fail_rate: float | None
    # R4: 1h tier flip count (None = unknown)
    tier_flip_1h: int | None
    # R5: health ok bool (None = probe failed)
    health_ok: bool | None


samples: Deque[Sample] = deque(maxlen=(SLIDING_WINDOW_S // SAMPLE_INTV_S) + 8)
ROLLBACK_FIRED = False


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only, no external deps)
# ---------------------------------------------------------------------------
def _json_get(url: str, timeout: float = 3.0) -> tuple[int, Any]:
    try:
        with urlrequest.urlopen(url, timeout=timeout) as r:
            body = r.read()
            return r.status, json.loads(body.decode("utf-8") or "null")
    except urlerr.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace") or "null")
        except Exception:
            return e.code, None
    except Exception as e:  # URLError / timeout / JSONDecode
        log.warning("GET %s failed: %s", url, e)
        return 0, None


def _api_key_from_envfile(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("MORE_SYSADMIN_API_KEY=") or line.startswith("SYSADMIN_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _post(url: str, body: dict, api_key: str | None, timeout=3.0) -> int:
    data = json.dumps(body).encode()
    req = urlrequest.Request(url, data=data, method="POST",
                             headers={"Content-Type": "application/json"})
    if api_key:
        req.add_header("X-API-Key", api_key)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as r:
            return r.status
    except urlerr.HTTPError as e:
        return e.code
    except Exception as e:
        log.warning("POST %s failed: %s", url, e)
        return 0


# ---------------------------------------------------------------------------
# 5 metrics probes
# ---------------------------------------------------------------------------
def _probe_r1_r5() -> tuple[float | None, bool | None]:
    """A2A echo against canary (latency ms) + canary /health."""
    t0 = time.monotonic()
    url = f"{CANARY_BASE}/api/v1/a2a"
    body = json.dumps({
        "method": "tasks/send",
        "params": {
            "task": {
                "messages": [{
                    "metadata": {"mode": "echo"},
                    "content": {"text": ECHO_TEXT, "_qnm_echo": True},
                }]
            }
        },
    }).encode()
    req = urlrequest.Request(url, data=body, method="POST",
                             headers={"Content-Type": "application/json"})
    echo_ms: float | None = None
    try:
        with urlrequest.urlopen(req, timeout=5.0) as r:
            echo_ms = (time.monotonic() - t0) * 1000.0
            try:
                payload = json.loads(r.read().decode() or "null") or {}
                got = ""
                try:
                    got = payload["result"]["task"]["messages"][-1]["content"]["text"]
                except Exception:
                    pass
                if got != ECHO_TEXT:
                    echo_ms = None  # corrupt = treat as fail
            except Exception:
                echo_ms = echo_ms
    except Exception as e:
        log.info("R1/R5 echo probe failed: %s", e)
        echo_ms = None

    # R5: health independently
    hstatus, hbody = _json_get(f"{CANARY_BASE}/api/v1/health", timeout=3.0)
    health_ok: bool | None
    if hstatus == 200 and isinstance(hbody, dict):
        health_ok = (hbody.get("status") == "healthy")
    elif hstatus == 0:
        health_ok = None
    else:
        health_ok = False
    return echo_ms, health_ok


def _probe_r2_r3() -> tuple[float | None, float | None]:
    """Evolution summary on canary → pass% + chassis delegation fail%."""
    _s, body = _json_get(f"{CANARY_BASE}/api/v1/evolution/summary", timeout=3.0)
    if not isinstance(body, dict):
        return None, None
    pass_pct: float | None = None
    del_fail_rate: float | None = None
    try:
        total = int(body.get("total_runs") or 0)
        passed = int(body.get("passed_runs") or 0)
        if total > 0:
            pass_pct = 100.0 * passed / total
    except Exception:
        pass_pct = None
    try:
        buckets = body.get("trigger_bucket_stats") or body.get("bucket_stats") or {}
        fails = 0
        totals = 0
        for key in ("chassis_default", "chassis_evolution"):
            b = buckets.get(key) if isinstance(buckets, dict) else None
            if isinstance(b, dict):
                tot = int(b.get("total") or 0)
                ok_ = int(b.get("ok") or 0)
                totals += tot
                fails += max(0, tot - ok_)
        if totals > 0:
            del_fail_rate = fails / totals
    except Exception:
        del_fail_rate = None
    return pass_pct, del_fail_rate


def _probe_r4() -> int | None:
    """Tier transitions 1h rolling count (P1-4 G-3 /llm/routing?tier_transitions_rollup=1h)."""
    url = f"{CANARY_BASE}/api/v1/llm/routing?tier_transitions_rollup=1h"
    _s, body = _json_get(url, timeout=3.0)
    if not isinstance(body, dict):
        return None
    # accept either key: tier_transitions_rollup.1h.count or transitions_last_1h
    rollup = body.get("tier_transitions_rollup") or body.get("rollup") or body
    try:
        if isinstance(rollup, dict) and "1h" in rollup:
            return int(rollup["1h"].get("count") or rollup["1h"].get("transitions") or 0)
        return int(body.get("transitions_last_1h") or body.get("tier_flip_1h") or 0)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Window → 5 Red Lights → Rollback
# ---------------------------------------------------------------------------
def _window_red_lights() -> dict[str, bool]:
    if not samples:
        return {k: False for k in ("R1", "R2", "R3", "R4", "R5")}
    min_samples = max(2, (SLIDING_WINDOW_S // SAMPLE_INTV_S) // 2)  # need half+ window

    # R1: every valid echo_ms >= 2000 AND no successful probe below threshold
    echo_ok = [s.echo_ms for s in samples if s.echo_ms is not None]
    r1 = (len(echo_ok) >= min_samples) and (
        len(echo_ok) > 0 and statistics.quantiles(echo_ok + echo_ok[-1:], n=20)[-1] >= RED_P95_MS
    )

    # R2: all pass_pct samples <= 25%
    pass_pcts = [s.pass_pct for s in samples if s.pass_pct is not None]
    r2 = (len(pass_pcts) >= min_samples) and (len(pass_pcts) > 0 and max(pass_pcts) <= RED_PASS_PCT)

    # R3: any sample fail_rate >= 5% sustained
    dfrs = [s.del_fail_rate for s in samples if s.del_fail_rate is not None]
    r3 = (len(dfrs) >= min_samples) and (len(dfrs) > 0 and min(dfrs) >= RED_DEL_FAIL)

    # R4: any sample tier_flip_1h >= 3
    tfs = [s.tier_flip_1h for s in samples if s.tier_flip_1h is not None]
    r4 = (len(tfs) >= min_samples // 2) and (len(tfs) > 0 and min(tfs) >= RED_TIER_FLIP_1H)

    # R5: all samples health_ok is False (100% unhealthy window)
    hvs = [s.health_ok for s in samples if s.health_ok is not None]
    r5 = (len(hvs) >= min_samples) and (len(hvs) > 0 and not any(hvs))

    return {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5}


_WEIGHT_RE = re.compile(
    r"server\s+127\.0\.0\.1:(?P<port>8765|8766)\s+weight=(?P<w>\d+)"
)


def _rewrite_nginx_weights(stable_w: int, canary_w: int) -> bool:
    if not NGINX_CONF.is_file():
        log.error("nginx conf not found: %s", NGINX_CONF)
        return False

    def _sub(m: re.Match) -> str:
        port = m.group("port")
        new_w = stable_w if port == "8765" else canary_w
        return f"server 127.0.0.1:{port} weight={new_w}"

    orig = NGINX_CONF.read_text()
    new_text, n = _WEIGHT_RE.subn(_sub, orig)
    if n < 2:
        log.error("substituted %d weight lines (<2 expected); abort rewrite", n)
        return False
    tmp = NGINX_CONF.with_suffix(NGINX_CONF.suffix + ".tmp")
    tmp.write_text(new_text)
    tmp.replace(NGINX_CONF)
    return True


def _nginx_reload() -> bool:
    try:
        r = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            log.error("nginx -t failed: %s\n%s", r.stdout, r.stderr)
            return False
        # Try passwordless sudo; fall back to direct (run as root-capable nginx user)
        cmds = [["sudo", "-n", "nginx", "-s", "reload"], ["nginx", "-s", "reload"]]
        for cmd in cmds:
            r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r2.returncode == 0:
                return True
            log.warning("nginx reload %s failed: rc=%d %s",
                        shlex.join(cmd), r2.returncode, r2.stderr.strip())
        return False
    except Exception as e:
        log.error("nginx reload exception: %s", e)
        return False


def fire_rollback(reason_lights: dict[str, bool], *, once: bool = True) -> bool:
    global ROLLBACK_FIRED
    if once and ROLLBACK_FIRED:
        return False
    ROLLBACK_FIRED = True

    log.critical("CANARY AUTO-ROLLBACK triggered. Red lights: %s",
                 {k: v for k, v in reason_lights.items() if v})
    ok_cfg = _rewrite_nginx_weights(100, 0)
    ok_rl  = _nginx_reload() if ok_cfg else False

    # P1-4 G-2: POST /ops/tier_rollback on canary (prev ladder) if RBAC key exists
    api_key = _api_key_from_envfile(API_KEY_FILE)
    if api_key:
        code = _post(f"{CANARY_BASE}/api/v1/ops/tier_rollback",
                     {"reason": f"canary rollback lights={reason_lights}"},
                     api_key, timeout=3.0)
        log.info("POST canary:/ops/tier_rollback status=%d", code)

    log.critical("Rollback result: cfg_rewritten=%s nginx_reloaded=%s. "
                 "Monitor will exit to avoid flapping (systemd Restart=on-failure).",
                 ok_cfg, ok_rl)
    # systemd Restart=on-failure + raise SIGTERM; we want on-demand restart only
    sys.exit(0 if (ok_cfg and ok_rl) else 1)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def _status_snapshot() -> str:
    latest = samples[-1] if samples else None
    rl = _window_red_lights()
    lines = []
    if latest is not None:
        lines.append(f"t={latest.t:.0f} echo_ms={latest.echo_ms} pass_pct={latest.pass_pct} "
                     f"del_fail={latest.del_fail_rate} tier_flip1h={latest.tier_flip_1h} "
                     f"health_ok={latest.health_ok}")
    lines.append(f"window_samples={len(samples)} red_lights={rl}")
    return " | ".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true",
                    help="Print one-liner window status & exit (used by more-rollout status)")
    ap.add_argument("--force-rollback", metavar="REASON",
                    help="Fire rollback immediately (CLI admin), then exit")
    args = ap.parse_args(argv)

    if args.force_rollback:
        fire_rollback({"CLI": True, "reason": args.force_rollback}, once=False)
        return 0

    if args.status:
        # populate window from files if any: /tmp/more-canary-samples.jsonl (future)
        print(_status_snapshot())
        return 0

    # graceful shutdown
    def _graceful(*_):
        log.info("canary-monitor shutting down on signal")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)

    log.info("canary-monitor start: stable=%s canary=%s chassis=%s nginx_conf=%s "
             "sample=%ss window=%ss",
             STABLE_BASE, CANARY_BASE, CHASSIS_BASE, NGINX_CONF,
             SAMPLE_INTV_S, SLIDING_WINDOW_S)

    while True:
        cycle_start = time.time()
        try:
            # 1) R1/R5 echo + health
            echo_ms, health_ok = _probe_r1_r5()
            # 2) R2/R3 evolution summary
            pass_pct, del_fail = _probe_r2_r3()
            # 3) R4 tier flips
            tier_flip = _probe_r4()
            samples.append(Sample(t=cycle_start,
                                  echo_ms=echo_ms,
                                  pass_pct=pass_pct,
                                  del_fail_rate=del_fail,
                                  tier_flip_1h=tier_flip,
                                  health_ok=health_ok))
            lights = _window_red_lights()
            if any(lights.values()):
                log.warning("Red light(s) active during this sample: %s", lights)
                fire_rollback(lights)
            else:
                log.info(_status_snapshot())
        except Exception as e:  # never die; sample cycle continues
            log.exception("sample cycle error: %s", e)

        sleep_for = max(0.1, SAMPLE_INTV_S - (time.time() - cycle_start))
        time.sleep(sleep_for)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
