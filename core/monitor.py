"""
core/monitor.py — Silverhand Network Monitor

Turns any device on the LAN into a command monitor. Checks reachability and
service ports for every host defined in the `network` section of agent.json,
and returns a structured snapshot the GUI renders as a live dashboard.

Checks are pure-Python (TCP connect + system ping) — no admin rights, no extra
deps, works the same on Windows and Linux. All hosts are probed concurrently so
a full snapshot stays well under the refresh interval.

CLI:
    python -m core.monitor          # one-shot text dump
    python -m core.monitor --watch  # refresh in place
"""

import platform
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from core.agent_loader import cfg

# ── Status codes ──────────────────────────────────────────────────────────────
UP       = "up"        # host reachable / port open
DOWN     = "down"      # host unreachable / port closed or filtered
UNKNOWN  = "unknown"   # not enough info (e.g. no probe ran)

_IS_WINDOWS = platform.system().lower().startswith("win")


# ── Low-level probes ──────────────────────────────────────────────────────────

def tcp_check(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
    """Try to open a TCP connection. Returns (open, latency_ms)."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency = (time.perf_counter() - start) * 1000.0
            return True, round(latency, 1)
    except OSError:
        return False, None


def ping_host(host: str, timeout: float) -> tuple[bool, float | None]:
    """
    Ping a host once via the system ping command. Returns (up, latency_ms).
    latency is parsed best-effort and may be None even when the host is up.
    """
    timeout_ms = max(1, int(timeout * 1000))
    if _IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        # -W is whole seconds on Linux ping; round up so we never pass 0.
        cmd = ["ping", "-c", "1", "-W", str(max(1, round(timeout))), host]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1.0,
            text=True,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False, None

    if proc.returncode != 0:
        return False, None

    # Best-effort latency parse ("time=12.3 ms" / "time=12ms" / "time<1ms").
    latency = None
    out = proc.stdout or ""
    marker = "time="
    idx = out.lower().find(marker)
    if idx != -1:
        tail = out[idx + len(marker):]
        num = ""
        for ch in tail:
            if ch.isdigit() or ch == ".":
                num += ch
            else:
                break
        if num:
            try:
                latency = round(float(num), 1)
            except ValueError:
                latency = None
    elif "time<" in out.lower():
        latency = 1.0
    return True, latency


# ── Host / service checks ─────────────────────────────────────────────────────

def _check_service(host_ip: str, svc: dict, timeout: float) -> dict:
    name = svc.get("name", f"port {svc.get('port')}")
    port = svc.get("port")
    if not isinstance(port, int):
        return {"name": name, "port": port, "status": UNKNOWN, "latency_ms": None}
    ok, latency = tcp_check(host_ip, port, timeout)
    return {
        "name": name,
        "port": port,
        "status": UP if ok else DOWN,
        "latency_ms": latency,
    }


def check_host(host_cfg: dict, timeout: float) -> dict:
    """Probe a single host and its services. Returns a status dict."""
    ip       = host_cfg.get("ip", "")
    services = host_cfg.get("services", []) or []

    # Run every service probe and the ping fallback concurrently so a fully-down
    # host costs ~one timeout instead of (services + ping) stacked in series.
    with ThreadPoolExecutor(max_workers=len(services) + 1) as pool:
        svc_futures = [pool.submit(_check_service, ip, s, timeout) for s in services]
        ping_future = pool.submit(ping_host, ip, timeout)
        svc_results = [f.result() for f in svc_futures]
        ping_up, ping_latency = ping_future.result()

    # Host is up if any service answered; otherwise trust the ping.
    open_svcs = [s for s in svc_results if s["status"] == UP]
    if open_svcs:
        up = True
        svc_latencies = [s["latency_ms"] for s in open_svcs if s["latency_ms"] is not None]
        latency = min(svc_latencies) if svc_latencies else ping_latency
    else:
        up, latency = ping_up, ping_latency

    return {
        "name":       host_cfg.get("name", ip),
        "ip":         ip,
        "role":       host_cfg.get("role", ""),
        "note":       host_cfg.get("note", ""),
        "status":     UP if up else DOWN,
        "latency_ms": latency,
        "services":   svc_results,
    }


def snapshot() -> dict:
    """
    Probe every configured host concurrently and return a full status snapshot:

        {
          "ts": <epoch seconds>,
          "generated_ms": <how long the sweep took>,
          "summary": {"total": N, "up": U, "down": D},
          "hosts": [ {host dict}, ... ]
        }
    """
    hosts   = cfg.net_hosts
    timeout = cfg.net_timeout_ms / 1000.0
    start   = time.perf_counter()

    if not hosts:
        return {
            "ts": time.time(),
            "generated_ms": 0.0,
            "summary": {"total": 0, "up": 0, "down": 0},
            "hosts": [],
        }

    max_workers = min(len(hosts) * 4, 32)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda h: check_host(h, timeout), hosts))

    up = sum(1 for h in results if h["status"] == UP)
    return {
        "ts":           time.time(),
        "generated_ms": round((time.perf_counter() - start) * 1000.0, 1),
        "summary":      {"total": len(results), "up": up, "down": len(results) - up},
        "hosts":        results,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_snapshot(snap: dict) -> None:
    s = snap["summary"]
    print(f"\n  SILVERHAND // NETWORK MONITOR   "
          f"[{s['up']}/{s['total']} up]   ({snap['generated_ms']} ms)")
    print("  " + "-" * 52)
    for h in snap["hosts"]:
        dot = "●" if h["status"] == UP else "○"
        lat = f"{h['latency_ms']} ms" if h["latency_ms"] is not None else "  --  "
        print(f"  {dot} {h['name']:<14} {h['ip']:<16} {h['status']:<5} {lat}")
        for svc in h["services"]:
            sdot = "▲" if svc["status"] == UP else "△"
            print(f"      {sdot} {svc['name']:<12} :{svc['port']:<6} {svc['status']}")
    print()


def main() -> None:
    import sys
    watch = "--watch" in sys.argv or "-w" in sys.argv
    if not watch:
        _print_snapshot(snapshot())
        return
    try:
        while True:
            snap = snapshot()
            # Clear screen (ANSI) then redraw.
            print("\033[2J\033[H", end="")
            _print_snapshot(snap)
            time.sleep(cfg.net_refresh_seconds)
    except KeyboardInterrupt:
        print("\n[monitor] Stopped.")


if __name__ == "__main__":
    main()
