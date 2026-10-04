#!/usr/bin/env python3
"""MoRE OS Prometheus Exporter (:9400 /metrics, Prometheus text 0.0.4 format).

Zero more_core source-code intrusion (G-2-6 compliant).

Metrics exposed (name pattern = more_*):
  R1 echo latency  -> more_canary_r1_echo_{p50,p95,p99}_ms
  R2 pass_rate     -> more_canary_r2_overall_pass_rate_pct
  R3 del fail rate -> more_canary_r3_delegation_fail_rate_pct
  R4 tier flips 1h -> more_canary_r4_tier_flips_1h
  R5 health        -> more_canary_r5_health{service="stable|canary|chassis"}
  lights           -> more_canary_light{id="R1|R2|R3|R4|R5"}
  nginx weights    -> more_nginx_weight{target="stable|canary"}
  evolution stats  -> more_evolution_total_runs / passed_runs / bias_applied_count / diff_uplift_count
  per-bucket rates -> more_evolution_pass_rate_pct{bucket="local|chassis_default|chassis_evolution"}
  per-bucket n/p   -> more_evolution_bucket_n{bucket=...} / bucket_passed
  version counts   -> more_evolution_sample_count{version="seed-10k|baseline"}
  systemd services -> more_systemd_active{service="<unit name>"}
  exporter self    -> more_exporter_last_scrape_success / scrape_duration_seconds

Run:
  python3 deploy/canary/scripts/more_prometheus_exporter.py [--port 9400] [--bind 127.0.0.1]

Docker-friendly: supports env MORE_EXPORTER_PORT / MORE_EXPORTER_BIND.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error as urlerr
from urllib import request as urlrequest

REPO_ROOT = Path(__file__).resolve().parents[3]
MORE_SRC = REPO_ROOT / "more_core"
sys.path.insert(0, str(MORE_SRC))

from more_core.codegen.evolution_signal import (  # noqa: E402
    _get_conn,
    _resolve_db_path,
    compute_evolution_summary,
)

# ---------------------------------------------------------------------------
# Defaults (override via env / CLI)
# ---------------------------------------------------------------------------
DEFAULT_PORT = int(os.getenv("MORE_EXPORTER_PORT", "9400"))
DEFAULT_BIND = os.getenv("MORE_EXPORTER_BIND", "127.0.0.1")

STABLE_BASE = os.getenv("MORE_CANARY_MON_STABLE",  "http://127.0.0.1:8765")
CANARY_BASE = os.getenv("MORE_CANARY_MON_CANARY",  "http://127.0.0.1:8766")
CHASSIS_BASE = os.getenv("MORE_CANARY_MON_CHASSIS","http://127.0.0.1:9988")
NGINX_CONF   = Path(os.getenv("MORE_CANARY_MON_NGINX_CONF",
                              str(REPO_ROOT / "deploy/canary/nginx/more_os_canary.conf")))
SYSTEMD_UNITS = {
    "stable":        "more-core-stable.service",
    "canary":        "more-core-canary.service",
    "chassis":       "blm-chassis.service",
    "canary-monitor":"canary-monitor.service",
}
# Canary thresholds (mirror canary_monitor.py constants)
RED_P95_MS   = 2000.0
RED_PASS_PCT = 25.0
RED_DEL_FAIL = 5.0
RED_TIER_FLIP_1H = 3

# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: float = 3.0) -> tuple[int, bytes | None]:
    try:
        with urlrequest.urlopen(url, timeout=timeout) as resp:
            return int(resp.getcode()), resp.read()
    except (urlerr.URLError, TimeoutError, socket.timeout, OSError):
        return 0, None


def _echo_probe_latencies(n: int = 11) -> list[float] | None:
    """POST chassis echo n times, return sorted latencies ms."""
    out: list[float] = []
    url = CHASSIS_BASE.rstrip("/") + "/"
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tasks/send",
        "params": {"content": {"_qnm_echo": True, "text": "prom-exporter-echo"},
                   "metadata": {"mode": "echo"}},
    }).encode("utf-8")
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            req = urlrequest.Request(
                url, data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlrequest.urlopen(req, timeout=2.5) as resp:
                resp.read()
            dt_ms = (time.perf_counter() - t0) * 1000.0
        except Exception:
            dt_ms = float("inf")
        out.append(dt_ms)
    if all(x == float("inf") for x in out):
        return None
    return sorted(x for x in out if x != float("inf"))


def _pct(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _tier_flips_1h() -> int:
    try:
        url = CANARY_BASE.rstrip("/") + "/api/v1/llm/routing?tier_transitions_rollup=1h"
        code, body = _http_get(url, timeout=2.5)
        if code == 200 and body:
            obj = json.loads(body.decode("utf-8", "ignore"))
            return int(obj.get("tier_transitions_per_hour")
                       or obj.get("transitions_last_1h") or obj.get("flips_1h") or 0)
    except Exception:
        pass
    # Fallback: compute via DB
    try:
        conn = _get_conn(_resolve_db_path(str(MORE_SRC)))
        try:
            rows = conn.execute(
                "SELECT created_at, tier_used, delegated, delegation_trigger FROM codegen_runs "
                "WHERE created_at > ? ORDER BY created_at",
                (time.time() - 3600,),
            ).fetchall()
        finally:
            conn.close()
        flips = 0
        last = None
        for _ts, t_raw, deleg, trig in rows:
            try:
                t = int(t_raw) if t_raw is not None else -1
            except Exception:
                t = -1
            if t < 0:
                if deleg and str(trig) == "evolution_escalation": t = 0
                elif deleg and str(trig) == "user_override": t = 1
                elif deleg and str(trig) == "default_gate": t = 2
                else: t = 1
            if last is not None and last != t:
                flips += 1
            last = t
        return flips
    except Exception:
        return 0


def _service_health(base: str) -> bool:
    code, body = _http_get(base.rstrip("/") + "/api/v1/health", timeout=2.5)
    if code != 200 or not body:
        return False
    try:
        obj = json.loads(body.decode("utf-8", "ignore"))
        return str(obj.get("status")).lower() == "healthy"
    except Exception:
        return False


def _chassis_health() -> bool:
    code, body = _http_get(CHASSIS_BASE.rstrip("/") + "/health", timeout=2.0)
    if code != 200:
        return False
    if body:
        try:
            obj = json.loads(body.decode("utf-8", "ignore"))
            if "status" in obj:
                return str(obj.get("status")).lower() in {"healthy", "ok", "up"}
        except Exception:
            pass
    return True


def _nginx_weights() -> tuple[int, int]:
    if not NGINX_CONF.exists():
        return 100, 0
    text = NGINX_CONF.read_text()
    m = re.findall(r"weight=(\d+)", text)
    if len(m) >= 2:
        try:
            return int(m[0]), int(m[1])
        except Exception:
            pass
    return 100, 0


def _systemd_active(unit: str) -> int:
    if shutil.which("systemctl"):
        try:
            r = subprocess.run(
                ["systemctl", "is-active", unit],
                timeout=2, capture_output=True, text=True,
            )
            return 1 if r.returncode == 0 and r.stdout.strip() == "active" else 0
        except Exception:
            return 0
    # MacOS / launchctl fallback: assume not running unless we can't detect ports
    # => use TCP port probe as proxy for stable/canary/chassis
    port_proxy = {
        "more-core-stable.service": 8765,
        "more-core-canary.service": 8766,
        "blm-chassis.service":      9988,
    }
    if unit in port_proxy:
        port = port_proxy[unit]
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return 1
        except OSError:
            return 0
    return 0


def _version_counts() -> dict[str, int]:
    out = {"seed-10k": 0, "baseline": 0}
    try:
        conn = _get_conn(_resolve_db_path(str(MORE_SRC)))
        try:
            try:
                (seed_n,) = conn.execute(
                    "SELECT COUNT(*) FROM codegen_runs WHERE "
                    "json_extract(artifacts_json, '$.version') = 'seed-10k'"
                ).fetchone()
            except sqlite3.OperationalError:
                # JSON1 not available -> fallback python decode
                seed_n = 0
                for (aj,) in conn.execute("SELECT artifacts_json FROM codegen_runs").fetchall():
                    try:
                        if json.loads(aj).get("version") == "seed-10k": seed_n += 1
                    except Exception: pass
            (total_n,) = conn.execute("SELECT COUNT(*) FROM codegen_runs").fetchone()
            out["seed-10k"] = int(seed_n or 0)
            out["baseline"] = int(total_n or 0) - out["seed-10k"]
        finally:
            conn.close()
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Scrape orchestrator
# ---------------------------------------------------------------------------

@dataclass
class Sample:
    name: str
    labels: dict[str, str]
    value: float | int


def scrape_all() -> tuple[list[Sample], list[tuple[str, str]], float, bool]:
    """Return (samples, metric_help_type, scrape_duration_seconds, success_bool)."""
    t0 = time.perf_counter()
    samples: list[Sample] = []
    help_type: list[tuple[str, str]] = []
    try:
        # -- R1: echo latencies (11 samples -> p50/p95/p99) --
        echo_ms = _echo_probe_latencies(n=11)
        if echo_ms:
            p50 = _pct(echo_ms, 0.50); p95 = _pct(echo_ms, 0.95); p99 = _pct(echo_ms, 0.99)
        else:
            p50 = p95 = p99 = 0.0
        samples.append(Sample("more_canary_r1_echo_p50_ms", {}, round(p50, 3)))
        samples.append(Sample("more_canary_r1_echo_p95_ms", {}, round(p95, 3)))
        samples.append(Sample("more_canary_r1_echo_p99_ms", {}, round(p99, 3)))
        samples.append(Sample("more_canary_r1_echo_samples_count", {}, int(len(echo_ms) if echo_ms else 0)))
        samples.append(Sample("more_canary_r1_echo_probe_success", {}, 1 if echo_ms else 0))
        help_type += [
            ("more_canary_r1_echo_p50_ms","gauge"),
            ("more_canary_r1_echo_p95_ms","gauge"),
            ("more_canary_r1_echo_p99_ms","gauge"),
            ("more_canary_r1_echo_samples_count","gauge"),
            ("more_canary_r1_echo_probe_success","gauge"),
        ]
        # -- Evolution summary (R2/R3 + evolution counters) --
        summary = compute_evolution_summary(project_root=str(MORE_SRC))
        total_runs = int(summary.get("total_runs") or 0)
        passed_runs = int(summary.get("passed_runs") or 0)
        pass_rate_pct = round(100.0 * float(summary.get("overall_pass_rate") or 0.0), 4)
        bac = int(summary.get("bias_applied_count") or 0)
        uplift = int(summary.get("bias_l1_diff_uplift_count") or 0)
        samples.append(Sample("more_canary_r2_overall_pass_rate_pct", {}, pass_rate_pct))
        samples.append(Sample("more_evolution_overall_fail_rate_pct", {}, round(100.0 - pass_rate_pct, 4)))
        help_type.append(("more_canary_r2_overall_pass_rate_pct", "gauge"))
        help_type.append(("more_evolution_overall_fail_rate_pct", "gauge"))
        samples.append(Sample("more_evolution_total_runs", {}, total_runs))
        samples.append(Sample("more_evolution_passed_runs", {}, passed_runs))
        samples.append(Sample("more_evolution_failed_runs", {}, total_runs - passed_runs))
        samples.append(Sample("more_evolution_bias_applied_count", {}, bac))
        samples.append(Sample("more_evolution_diff_uplift_count", {}, uplift))
        help_type += [
            ("more_evolution_total_runs","gauge"),
            ("more_evolution_passed_runs","gauge"),
            ("more_evolution_failed_runs","gauge"),
            ("more_evolution_bias_applied_count","gauge"),
            ("more_evolution_diff_uplift_count","gauge"),
        ]
        # R3 delegation fail rate = weighted avg of 1-rate across 2 chassis buckets (fail = 100-rate)
        rates = summary.get("strategy_rates") or {}
        def _b(key):
            r = rates.get(key, {}); n = int(r.get("n") or 0); p = int(r.get("passed") or 0)
            rate = (p/n) if n else 0.0
            return n, p, rate
        local_n, local_p, local_rate = _b("local")
        cd_n, cd_p, cd_rate = _b("chassis_default")
        ce_n, ce_p, ce_rate = _b("chassis_evolution")
        total_del = cd_n + ce_n
        if total_del > 0:
            fail_rate_pct = 100.0 * ( ((cd_n*(1-cd_rate)) + (ce_n*(1-ce_rate))) / total_del )
        else:
            fail_rate_pct = 0.0
        samples.append(Sample("more_canary_r3_delegation_fail_rate_pct", {}, round(fail_rate_pct, 4)))
        help_type.append(("more_canary_r3_delegation_fail_rate_pct", "gauge"))
        # per-bucket
        for bkey, bn, bp, br in (
            ("local", local_n, local_p, local_rate),
            ("chassis_default", cd_n, cd_p, cd_rate),
            ("chassis_evolution", ce_n, ce_p, ce_rate),
        ):
            samples.append(Sample("more_evolution_bucket_n",        {"bucket": bkey}, bn))
            samples.append(Sample("more_evolution_bucket_passed",   {"bucket": bkey}, bp))
            samples.append(Sample("more_evolution_pass_rate_pct",   {"bucket": bkey}, round(100.0*br, 4)))
        help_type += [
            ("more_evolution_bucket_n","gauge"),
            ("more_evolution_bucket_passed","gauge"),
            ("more_evolution_pass_rate_pct","gauge"),
        ]
        # -- R4 tier flips --
        flips = _tier_flips_1h()
        samples.append(Sample("more_canary_r4_tier_flips_1h", {}, int(flips or 0)))
        help_type.append(("more_canary_r4_tier_flips_1h","gauge"))
        # -- R5 health --
        r5_stable = 1 if _service_health(STABLE_BASE) else 0
        r5_canary = 1 if _service_health(CANARY_BASE) else 0
        r5_chassis = 1 if _chassis_health() else 0
        for svc, val in (("stable", r5_stable), ("canary", r5_canary), ("chassis", r5_chassis)):
            samples.append(Sample("more_canary_r5_health", {"service": svc}, val))
        samples.append(Sample("more_canary_r5_services_monitored", {}, 3))
        samples.append(Sample("more_canary_r5_healthy_count", {}, int(r5_stable + r5_canary + r5_chassis)))
        samples.append(Sample("more_canary_r5_unhealthy_count", {}, int(3 - (r5_stable + r5_canary + r5_chassis))))
        help_type.append(("more_canary_r5_health","gauge"))
        help_type.append(("more_canary_r5_services_monitored","gauge"))
        help_type.append(("more_canary_r5_healthy_count","gauge"))
        help_type.append(("more_canary_r5_unhealthy_count","gauge"))
        # -- 5 red lights --
        lights = {
            "R1": 1 if (echo_ms is not None and p95 >= RED_P95_MS) else (0 if echo_ms else 0),
            "R2": 1 if pass_rate_pct <= RED_PASS_PCT else 0,
            "R3": 1 if fail_rate_pct >= RED_DEL_FAIL else 0,
            "R4": 1 if flips >= RED_TIER_FLIP_1H else 0,
            "R5": 1 if (r5_stable + r5_canary + r5_chassis) < 3 else 0,
        }
        for rid, val in lights.items():
            samples.append(Sample("more_canary_light", {"id": rid}, val))
        help_type.append(("more_canary_light","gauge"))
        # -- Nginx weights --
        sw, cw = _nginx_weights()
        samples.append(Sample("more_nginx_weight", {"target": "stable"},  sw))
        samples.append(Sample("more_nginx_weight", {"target": "canary"},  cw))
        samples.append(Sample("more_nginx_weight_sum", {}, int((sw or 0) + (cw or 0))))
        samples.append(Sample("more_nginx_weight_canary_ratio_pct",
            {},
            round(100.0 * (cw or 0) / max(1, (sw or 0) + (cw or 0)), 3)))
        help_type.append(("more_nginx_weight","gauge"))
        help_type.append(("more_nginx_weight_sum","gauge"))
        help_type.append(("more_nginx_weight_canary_ratio_pct","gauge"))
        # -- version counts --
        for ver, cnt in _version_counts().items():
            samples.append(Sample("more_evolution_sample_count", {"version": ver}, int(cnt)))
        help_type.append(("more_evolution_sample_count","gauge"))
        # -- systemd --
        for tag, unit in SYSTEMD_UNITS.items():
            samples.append(Sample("more_systemd_active", {"service": tag}, _systemd_active(unit)))
        help_type.append(("more_systemd_active","gauge"))
        # derived canary-vs-local pass rate delta (chassis_evolution − local; chassis_default − local)
        def _rate_pct(n_,p_): return (100.0 * p_ / n_) if n_ else 0.0
        for bucket in ("chassis_default","chassis_evolution"):
            bn = rates.get(bucket,{}).get("n") or 0
            bp = rates.get(bucket,{}).get("passed") or 0
            samples.append(Sample("more_evolution_pass_rate_delta_vs_local_pct",
                {"bucket": bucket},
                round(_rate_pct(bn,bp) - _rate_pct(local_n, local_p), 4)))
        help_type.append(("more_evolution_pass_rate_delta_vs_local_pct","gauge"))
        success = True
    except Exception:
        traceback.print_exc()
        success = False
    dur = time.perf_counter() - t0
    samples.append(Sample("more_exporter_last_scrape_success", {}, 1 if success else 0))
    samples.append(Sample("more_exporter_scrape_duration_seconds", {}, round(dur, 6)))
    help_type += [
        ("more_exporter_last_scrape_success","gauge"),
        ("more_exporter_scrape_duration_seconds","gauge"),
    ]
    return samples, help_type, dur, success


# ---------------------------------------------------------------------------
# Prometheus text format renderer
# ---------------------------------------------------------------------------

_METRIC_HELP = {
    "more_canary_r1_echo_p50_ms": "R1 echo latency p50 in ms (chassis tasks/send echo, n=11 samples)",
    "more_canary_r1_echo_p95_ms": "R1 echo latency p95 in ms; RED >= 2000ms",
    "more_canary_r1_echo_p99_ms": "R1 echo latency p99 in ms",
    "more_canary_r1_echo_samples_count": "R1 echo probe effective samples count (n)",
    "more_canary_r1_echo_probe_success": "R1 echo probe succeeded (1=ok, 0=timeout/error)",
    "more_canary_r2_overall_pass_rate_pct": "R2 evolution overall pass rate %; RED <= 25%",
    "more_evolution_overall_fail_rate_pct": "Evolution overall fail rate = 100 − pass_rate %",
    "more_canary_r3_delegation_fail_rate_pct": "R3 chassis delegation failure rate %; RED >= 5%",
    "more_canary_r4_tier_flips_1h": "R4 LLM tier flips counted across last 1h; RED >= 3",
    "more_canary_r5_health": "R5 /api/v1/health probe per service (1 = healthy)",
    "more_canary_r5_services_monitored": "R5 total services monitored cardinality (fixed 3)",
    "more_canary_r5_healthy_count": "R5 services currently healthy (0..3)",
    "more_canary_r5_unhealthy_count": "R5 services currently unhealthy (0..3)",
    "more_canary_light": "Canary red-light state per R[1-5] id (1 = RED, 0 = normal)",
    "more_nginx_weight": "Nginx upstream weight by target (stable / canary)",
    "more_nginx_weight_sum": "Sum of nginx stable + canary weights (should equal total round-robin unit)",
    "more_nginx_weight_canary_ratio_pct": "Canary share of nginx total weight in %",
    "more_evolution_total_runs": "Evolution DB codegen_runs total count",
    "more_evolution_passed_runs": "Evolution DB passed runs (decision='pass')",
    "more_evolution_failed_runs": "Evolution DB failed runs (total − passed)",
    "more_evolution_bias_applied_count": "Evolution runs with delegation-bias applied tag",
    "more_evolution_diff_uplift_count": "Evolution runs with L1 difficulty uplift bias",
    "more_evolution_bucket_n": "Evolution runs n per delegation bucket",
    "more_evolution_bucket_passed": "Evolution runs passed per delegation bucket",
    "more_evolution_pass_rate_pct": "Evolution pass rate % per delegation bucket",
    "more_evolution_pass_rate_delta_vs_local_pct": "Bucket pass rate MINUS local pass rate in pp (expected ≥ 5pp per ADR)",
    "more_evolution_sample_count": "Evolution runs per version tag (seed-10k / baseline)",
    "more_systemd_active": "1 if the given systemd unit is active, else 0",
    "more_exporter_last_scrape_success": "1 if the last exporter scrape finished without exception",
    "more_exporter_scrape_duration_seconds": "Wall-clock seconds spent on the most recent scrape",
}


def render_prom(samples: list[Sample], help_type: list[tuple[str, str]]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    type_order: dict[str, str] = {m: t for m, t in help_type}
    by_metric: dict[str, list[Sample]] = {}
    for s in samples:
        by_metric.setdefault(s.name, []).append(s)
    # Preserve declaration order
    declared = [m for m, _ in help_type] + [m for m in by_metric if m not in {x for x,_ in help_type}]
    # dedupe
    emitted: list[str] = []
    for m in declared:
        if m in emitted: continue
        emitted.append(m)
        rows = by_metric.get(m, [])
        if not rows: continue
        mtype = type_order.get(m, "gauge")
        lines.append(f"# HELP {m} {_METRIC_HELP.get(m, '')}")
        lines.append(f"# TYPE {m} {mtype}")
        for s in rows:
            if s.labels:
                lpairs = ",".join(f'{k}="{v}"' for k, v in s.labels.items())
                lines.append(f"{m}{{{lpairs}}} {s.value}")
            else:
                lines.append(f"{m} {s.value}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class ExporterHandler(BaseHTTPRequestHandler):
    server_version = "MoreExporter/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # silence default stderr log
        return

    def do_GET(self) -> None:
        if self.path in ("/metrics", "/metrics/"):
            try:
                samples, ht, _dur, ok = scrape_all()
                body = render_prom(samples, ht).encode("utf-8")
                self.send_response(200 if ok else 503)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = f"# scrape error: {exc}\n".encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(body)
            return
        if self.path in ("/", "/healthz"):
            body = b"more_prometheus_exporter ok\nGET /metrics for Prometheus text format\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"not found\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MoRE OS Prometheus Exporter")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--bind", type=str, default=DEFAULT_BIND)
    ap.add_argument("--once", action="store_true",
                    help="Do not start HTTP server; print one scrape to stdout and exit.")
    args = ap.parse_args(argv)
    if args.once:
        samples, ht, dur, ok = scrape_all()
        sys.stdout.write(render_prom(samples, ht))
        print(f"# scrape_duration={dur:.3f}s success={ok}", file=sys.stderr)
        return 0 if ok else 2
    addr = (args.bind, args.port)
    httpd = ThreadingHTTPServer(addr, ExporterHandler)
    print(f"more_prometheus_exporter listening on http://{addr[0]}:{addr[1]}/metrics", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
