"""
satellite.py — Silverhand Satellite Bridge
D:\\Silverhand\\core\\satellite.py

WebSocket server that the Waveshare AMOLED S3 connects to.
Serves:
  - PC metrics (CPU, GPU, RAM, temps) via psutil + pynvml
  - LAN network scan (ARP table) via subprocess arp -a
  - Talk pipeline: receives audio trigger → runs Silverhand STT→LLM→TTS
    and returns text reply to board display

Run: python core\\satellite.py
Or integrated into main.py as a background thread (see bottom of file).

Port: 8877 (add Windows Firewall rule for LAN-only access)
"""

import asyncio
import json
import logging
import subprocess
import re
import threading
import time
from typing import Set

import websockets
import numpy as np
import requests as _requests
import psutil

from core.stt import _get_model
from core.llm import build_messages
from core.agent_loader import cfg

# pynvml for RTX 4070 Ti precise GPU metrics
try:
    import pynvml
    pynvml.nvmlInit()
    _nvml_ok = True
except Exception:
    _nvml_ok = False

logging.basicConfig(level=logging.INFO, format="[SAT] %(message)s")
log = logging.getLogger("satellite")

BRIDGE_PORT = 8877
METRICS_CACHE_TTL = 1.5   # seconds — don't hammer psutil
NETWORK_CACHE_TTL = 10.0  # ARP scan is slow, cache it
LLM_MODEL = "hermes-3-llama-3.1-8b"

# ─── CONNECTED CLIENTS ────────────────────────────────────────────
clients: Set[websockets.WebSocketServerProtocol] = set()

# ─── METRICS CACHE ────────────────────────────────────────────────
_metrics_cache = {}
_metrics_ts    = 0.0
_network_cache = []
_network_ts    = 0.0
_net_prev      = None   # (bytes_sent, bytes_recv, timestamp)

# ─── TALK STATE ───────────────────────────────────────────────────
_talk_state: dict = {}   # websocket id → {"buf": bytearray, "history": []}


# ═══════════════════════════════════════════════════════════════════
#  METRICS
# ═══════════════════════════════════════════════════════════════════

def get_metrics() -> dict:
    global _metrics_cache, _metrics_ts
    now = time.monotonic()
    if now - _metrics_ts < METRICS_CACHE_TTL and _metrics_cache:
        return _metrics_cache

    # CPU
    cpu_pct  = psutil.cpu_percent(interval=0.5)
    cpu_temp = 0.0
    try:
        temps = psutil.sensors_temperatures()
        # Try common Windows keys
        for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if key in temps and temps[key]:
                cpu_temp = temps[key][0].current
                break
    except Exception:
        pass

    # RAM
    ram     = psutil.virtual_memory()
    ram_pct = ram.percent
    ram_used_gb  = ram.used  / (1024**3)
    ram_total_gb = ram.total / (1024**3)

    # Network throughput
    global _net_prev
    net_up_bps = 0
    net_down_bps = 0
    try:
        nc = psutil.net_io_counters()
        if _net_prev is not None:
            prev_sent, prev_recv, prev_t = _net_prev
            dt = now - prev_t
            if dt > 0:
                net_up_bps   = int((nc.bytes_sent - prev_sent) / dt)
                net_down_bps = int((nc.bytes_recv - prev_recv) / dt)
        _net_prev = (nc.bytes_sent, nc.bytes_recv, now)
    except Exception:
        pass

    # GPU via pynvml (RTX 4070 Ti)
    gpu_pct  = 0
    gpu_temp = 0.0
    if _nvml_ok:
        try:
            handle   = pynvml.nvmlDeviceGetHandleByIndex(0)
            util     = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp_val = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            gpu_pct  = util.gpu
            gpu_temp = float(temp_val)
        except Exception as e:
            log.warning(f"nvml read failed: {e}")

    _metrics_cache = {
        "type":         "metrics",
        "cpu_pct":      int(cpu_pct),
        "gpu_pct":      int(gpu_pct),
        "ram_pct":      int(ram_pct),
        "ram_used_gb":  round(ram_used_gb, 1),
        "ram_total_gb": round(ram_total_gb, 1),
        "cpu_temp":     round(cpu_temp, 1),
        "gpu_temp":     round(gpu_temp, 1),
        "net_up_bps":   net_up_bps,
        "net_down_bps": net_down_bps,
    }
    _metrics_ts = now
    return _metrics_cache


# ═══════════════════════════════════════════════════════════════════
#  NETWORK SCAN
# ═══════════════════════════════════════════════════════════════════

# Known hostname hints for your LAN
KNOWN_HOSTS = {
    "10.0.0.1":  "router",
    "10.0.0.66": "silverhand-pc",
    "10.0.0.67": "nas",          # update to actual NAS IP
}

def arp_scan() -> list:
    """Read Windows ARP table — no admin needed, no nmap required."""
    devices = []
    try:
        result = subprocess.run(
            ["arp", "-a"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        for line in lines:
            # Match lines like:   10.0.0.1    aa-bb-cc-dd-ee-ff    dynamic
            m = re.match(r"\s+(10\.\d+\.\d+\.\d+)\s+([\w-]+)\s+(\w+)", line)
            if m:
                ip     = m.group(1)
                mac    = m.group(2)
                kind   = m.group(3)  # dynamic / static
                if kind.lower() in ("dynamic", "static"):
                    hostname = KNOWN_HOSTS.get(ip, _vendor_hint(mac))
                    devices.append({
                        "ip":       ip,
                        "hostname": hostname,
                        "mac":      mac,
                        "online":   True,
                    })
    except Exception as e:
        log.warning(f"ARP scan failed: {e}")
    return devices


def _vendor_hint(mac: str) -> str:
    """Very rough MAC OUI → vendor label. Extend as needed."""
    prefix = mac.upper().replace("-", ":")[:8]
    oui_map = {
        "00:50:56": "vmware",
        "B8:27:EB": "raspi",
        "DC:A6:32": "raspi",
        "18:31:BF": "msi",
        "00:1A:11": "google",
        "AC:BC:32": "apple",
    }
    return oui_map.get(prefix, "device")


def get_network() -> dict:
    global _network_cache, _network_ts
    now = time.monotonic()
    if now - _network_ts < NETWORK_CACHE_TTL and _network_cache:
        return {"type": "network", "devices": _network_cache}
    _network_cache = arp_scan()
    _network_ts = now
    return {"type": "network", "devices": _network_cache}



# ═══════════════════════════════════════════════════════════════════
#  AUDIO PROCESSING — faster-whisper STT + LLM pipeline
# ═══════════════════════════════════════════════════════════════════

def _process_audio(buf: bytearray, history: list) -> str:
    seconds = len(buf) / 32000  # 16kHz × 16-bit mono = 32000 bytes/s
    log.info(f"Audio received: {len(buf)} bytes ({seconds:.1f}s)")

    # Convert int16 PCM → float32 normalised
    audio = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0

    # Silence check
    if len(audio) == 0 or np.max(np.abs(audio)) < 0.005:
        log.info("Audio too quiet or empty — skipping STT")
        return "I didn't catch that."

    # Transcribe
    try:
        model = _get_model()
        segments, _ = model.transcribe(audio, beam_size=5, language="en")
        text = " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:
        log.warning(f"STT failed: {e}")
        return "I didn't catch that."

    if not text:
        return "I didn't catch that."
    log.info(f"Heard: {text}")

    # LLM — inline call with max_tokens=80 (llm.chat() hardcodes 600)
    messages = build_messages(history, text)
    try:
        resp = _requests.post(
            f"http://127.0.0.1:{cfg.llm_port}/v1/chat/completions",
            json={
                "model":       LLM_MODEL,
                "messages":    messages,
                "max_tokens":  80,
                "temperature": 0.75,
                "stream":      False,
            },
            timeout=90,
        )
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"LLM failed: {e}")
        return "Lost the signal."

    if not reply:
        return "Lost the signal."

    # Append to session history — only on success
    history.append({"role": "user",      "content": text})
    history.append({"role": "assistant", "content": reply})
    return reply


# ═══════════════════════════════════════════════════════════════════
#  WEBSOCKET HANDLER
# ═══════════════════════════════════════════════════════════════════

async def handler(websocket):
    clients.add(websocket)
    remote = websocket.remote_address
    log.info(f"Client connected: {remote}")
    try:
        async for msg in websocket:
            if isinstance(msg, bytes):
                # binary frame — audio chunk from board
                state = _talk_state.get(id(websocket))
                if state:
                    state["buf"].extend(msg)
                continue

            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue

            cmd = data.get("cmd", "")

            if cmd == "hello":
                log.info(f"Satellite hello from {data.get('client','?')}")
                await websocket.send(json.dumps({
                    "type": "hello_ack",
                    "server": "silverhand-bridge",
                    "version": "1.0"
                }))

            elif cmd == "get_metrics":
                await websocket.send(json.dumps(get_metrics()))

            elif cmd == "get_network":
                await websocket.send(json.dumps(get_network()))

            elif cmd == "talk_start":
                _talk_state[id(websocket)] = {"buf": bytearray(), "history": []}
                log.info("Talk started")

            elif cmd == "talk_end":
                state = _talk_state.pop(id(websocket), None)
                if state:
                    loop = asyncio.get_running_loop()
                    reply = await loop.run_in_executor(
                        None, _process_audio, state["buf"], state["history"]
                    )
                    await websocket.send(json.dumps({
                        "type": "reply",
                        "text": reply
                    }))

            elif cmd == "talk_cancel":
                _talk_state.pop(id(websocket), None)
                log.info("Talk cancelled")

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _talk_state.pop(id(websocket), None)
        clients.discard(websocket)
        log.info(f"Client disconnected: {remote}")


# ═══════════════════════════════════════════════════════════════════
#  PUSH LOOP — proactively push metrics every 2.5s to all clients
# ═══════════════════════════════════════════════════════════════════

async def push_metrics_loop():
    """Push metrics to all connected clients without waiting for poll."""
    while True:
        await asyncio.sleep(2.5)
        if not clients:
            continue
        data = json.dumps(get_metrics())
        dead = set()
        for ws_client in clients:
            try:
                await ws_client.send(data)
            except Exception:
                dead.add(ws_client)
        clients.difference_update(dead)


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

async def _serve():
    log.info(f"Silverhand bridge starting on port {BRIDGE_PORT}")
    async with websockets.serve(handler, "0.0.0.0", BRIDGE_PORT):
        await asyncio.gather(
            asyncio.Future(),   # run forever
            push_metrics_loop(),
        )


def start_in_thread():
    """
    Call this from main.py to run satellite in a background thread.

    In main.py, after imports:

        from core.satellite import start_in_thread as start_satellite
        start_satellite()

    That's it — bridge runs alongside the voice pipeline.
    """
    def _run():
        asyncio.run(_serve())
    t = threading.Thread(target=_run, name="satellite-bridge", daemon=True)
    t.start()
    log.info("Satellite bridge thread started")
    return t


if __name__ == "__main__":
    # Standalone mode: python core\\satellite.py
    asyncio.run(_serve())
