"""
ui/gui.py — Silverhand GUI bridge (WebSocket edition)
Spins up a local FastAPI server. The HTML page connects via WS.
Push events to the GUI via gui.send(event_dict) from any thread.

Server:    http://127.0.0.1:7477
WebSocket: ws://127.0.0.1:7477/ws
"""

import asyncio
import json
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.agent_loader import cfg
from core import monitor

# ── Config ────────────────────────────────────────────────────────────────────

HOST         = cfg.gui_host                 # "0.0.0.0" exposes it to the LAN
PORT         = cfg.gui_port
UI_DIR       = Path(__file__).parent        # D:\Silverhand\ui\
HTML_FILE    = UI_DIR / "silverhand.html"
MONITOR_FILE = UI_DIR / "monitor.html"
LAUNCH_FILE  = UI_DIR.parent / "tablet" / "command-center.html"

# ── State ─────────────────────────────────────────────────────────────────────

_app                              = FastAPI()
_loop: asyncio.AbstractEventLoop | None = None
_clients: list[WebSocket]         = []
_on_text_cb                       = None
_on_name_request_cb               = None
_ready                            = threading.Event()

# ── Static assets ─────────────────────────────────────────────────────────────

assets_dir = UI_DIR / "assets"
assets_dir.mkdir(exist_ok=True)
_app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

# ── Routes ────────────────────────────────────────────────────────────────────

@_app.get("/")
async def index():
    return FileResponse(str(HTML_FILE))


@_app.get("/monitor")
async def monitor_page():
    """Network command monitor — open this from the tablet."""
    return FileResponse(str(MONITOR_FILE))


@_app.get("/launch")
async def launch_page():
    """
    Zero-copy tablet launcher: browse to http://<pc-ip>:7477/launch and the
    page auto-fills the host from the address you reached it on.
    """
    return FileResponse(str(LAUNCH_FILE))


@_app.get("/api/monitor")
def monitor_api():
    """
    Live network snapshot as JSON. Defined as a sync endpoint so FastAPI runs
    the blocking socket/ping probes in its threadpool without stalling the loop.
    """
    return JSONResponse(monitor.snapshot())


@_app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.append(ws)
    print(f"[gui] Browser connected ({len(_clients)} client(s))")
    _ready.set()
    try:
        while True:
            data = await ws.receive_text()
            msg  = json.loads(data)
            if msg.get("type") == "user_text" and _on_text_cb:
                threading.Thread(
                    target=_on_text_cb,
                    args=(msg.get("text", ""),),
                    daemon=True
                ).start()
            elif msg.get("type") == "request_name" and _on_name_request_cb:
                # Browser just connected/reconnected — push name again
                threading.Thread(target=_on_name_request_cb, daemon=True).start()
    except WebSocketDisconnect:
        if ws in _clients:
            _clients.remove(ws)
        print(f"[gui] Browser disconnected ({len(_clients)} client(s))")


# ── Broadcast ─────────────────────────────────────────────────────────────────

async def _broadcast(payload: str):
    dead = []
    for ws in list(_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _clients:
            _clients.remove(ws)


def _send_from_thread(event: dict):
    if _loop and not _loop.is_closed():
        asyncio.run_coroutine_threadsafe(
            _broadcast(json.dumps(event)), _loop
        )


# ── Public API ────────────────────────────────────────────────────────────────

def send(event: dict):
    """Push any event dict to all connected browser clients."""
    _send_from_thread(event)


def on_listening():            send({"type": "listening"})
def on_user_input(text: str):  send({"type": "user_input",  "text": text})
def on_thinking():             send({"type": "thinking"})
def on_response(text: str):    send({"type": "response",    "text": text})
def on_speaking():             send({"type": "response_start"})
def on_idle():                 send({"type": "idle"})
def on_mode_change(mode: str): send({"type": "mode_change", "mode": mode})


def wait_ready(timeout: float = 30):
    """Block until at least one browser tab has connected."""
    _ready.wait(timeout=timeout)


# ── Server startup ────────────────────────────────────────────────────────────

def _run_server():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    config = uvicorn.Config(
        app       = _app,
        host      = HOST,
        port      = PORT,
        loop      = "none",
        log_level = "warning",
    )
    server = uvicorn.Server(config)
    _loop.run_until_complete(server.serve())


def start(on_text_input=None, on_name_request=None, open_browser: bool = True):
    """
    Start GUI server in a background thread, optionally open the browser.

    Args:
        on_text_input:   callback(text: str) fired when user types in the GUI
        on_name_request: callback() fired when browser connects/reconnects — should push set_name
        open_browser:    auto-open http://127.0.0.1:7477 in default browser
    """
    global _on_text_cb, _on_name_request_cb
    _on_text_cb         = on_text_input
    _on_name_request_cb = on_name_request

    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    # 0.0.0.0 is a bind address, not something a browser can open — use loopback.
    local_host = "127.0.0.1" if HOST in ("0.0.0.0", "::") else HOST

    if open_browser:
        threading.Timer(
            1.2, lambda: webbrowser.open(f"http://{local_host}:{PORT}")
        ).start()

    print(f"[gui] Server listening on {HOST}:{PORT}")
    print(f"[gui] Assistant UI:    http://{local_host}:{PORT}/")
    print(f"[gui] Command monitor: http://{local_host}:{PORT}/monitor")
    if HOST in ("0.0.0.0", "::"):
        print(f"[gui] Reachable from other devices at http://<this-pc-ip>:{PORT}/monitor")
    print(f"[gui] Waiting for browser...")
    return t
