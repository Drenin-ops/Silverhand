# core\tray.py
# System tray icon for Silverhand.
# Runs in a daemon thread — never blocks the main loop.
#
# Public API:
#   start(on_open_gui, on_toggle_mode, on_mute_toggle, on_exit)
#   set_state(state: str)   — "idle" | "listening" | "thinking" | "speaking" | "muted" | "error"
#   is_muted() -> bool
#   stop()

import threading
import webbrowser
from PIL import Image, ImageDraw
import pystray

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GUI_URL = "http://127.0.0.1:7477"

ICON_SIZE = 64  # px, square

# State → RGB fill color for the icon dot
STATE_COLORS = {
    "idle":      (0,   200, 80),   # green
    "listening": (255, 180, 0),    # amber
    "thinking":  (255, 140, 0),    # orange-amber
    "speaking":  (0,   160, 255),  # blue
    "muted":     (120, 120, 120),  # grey
    "error":     (220, 40,  40),   # red
}

DEFAULT_STATE = "idle"

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_tray:        pystray.Icon | None = None
_tray_thread: threading.Thread   | None = None
_muted        = False
_current_state = DEFAULT_STATE
_lock          = threading.Lock()

# Callbacks — set by start()
_cb_open_gui     = None
_cb_toggle_mode  = None
_cb_mute_toggle  = None
_cb_exit         = None

# ---------------------------------------------------------------------------
# Icon drawing
# ---------------------------------------------------------------------------

def _make_icon_image(state: str) -> Image.Image:
    """Draw a square icon: dark background + colored circle."""
    color = STATE_COLORS.get(state, STATE_COLORS["idle"])
    img   = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (20, 20, 20, 255))
    draw  = ImageDraw.Draw(img)

    margin = ICON_SIZE // 8
    draw.ellipse(
        [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
        fill=color,
    )
    return img


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------

def _mode_label(item=None) -> str:
    """Deferred label so menu reflects current trigger mode."""
    try:
        from core import trigger
        mode = trigger.get_mode().upper()
        return f"Mode: {mode} (toggle)"
    except Exception:
        return "Toggle Mode"


def _mute_label(item=None) -> str:
    return "Unmute TTS" if _muted else "Mute TTS"


def _build_menu() -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem("Open GUI",          _action_open_gui),
        pystray.MenuItem(_mode_label,         _action_toggle_mode),
        pystray.MenuItem(_mute_label,         _action_mute_toggle),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit",              _action_exit),
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _action_open_gui(icon, item):
    webbrowser.open(GUI_URL)
    if _cb_open_gui:
        _cb_open_gui()


def _action_toggle_mode(icon, item):
    if _cb_toggle_mode:
        new_mode = _cb_toggle_mode()
        # Redraw menu so label updates
        if _tray:
            _tray.menu = _build_menu()
            _tray.update_menu()


def _action_mute_toggle(icon, item):
    global _muted
    with _lock:
        _muted = not _muted
    if _cb_mute_toggle:
        _cb_mute_toggle(_muted)
    # Update icon to reflect mute state
    effective = "muted" if _muted else _current_state
    _apply_icon(effective)
    if _tray:
        _tray.menu = _build_menu()
        _tray.update_menu()


def _action_exit(icon, item):
    stop()
    if _cb_exit:
        _cb_exit()


# ---------------------------------------------------------------------------
# Icon update
# ---------------------------------------------------------------------------

def _apply_icon(state: str):
    """Push a new icon image to the tray (thread-safe)."""
    if _tray is None:
        return
    try:
        _tray.icon = _make_icon_image(state)
    except Exception:
        pass  # tray may not be fully ready yet


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def set_state(state: str):
    """
    Update tray icon color to reflect current assistant state.
    state: "idle" | "listening" | "thinking" | "speaking" | "muted" | "error"
    Muted state overrides everything visually while mute is active.
    """
    global _current_state
    with _lock:
        _current_state = state
    effective = "muted" if _muted else state
    _apply_icon(effective)


def is_muted() -> bool:
    return _muted


def start(
    on_open_gui    = None,
    on_toggle_mode = None,
    on_mute_toggle = None,
    on_exit        = None,
):
    """
    Start the tray icon in a background daemon thread.

    Callbacks:
        on_open_gui()           — called when user clicks Open GUI
        on_toggle_mode() -> str — called on toggle; should return new mode string
        on_mute_toggle(muted: bool) — called after mute flip
        on_exit()               — called when user clicks Exit
    """
    global _tray, _tray_thread
    global _cb_open_gui, _cb_toggle_mode, _cb_mute_toggle, _cb_exit

    _cb_open_gui    = on_open_gui
    _cb_toggle_mode = on_toggle_mode
    _cb_mute_toggle = on_mute_toggle
    _cb_exit        = on_exit

    icon_image = _make_icon_image(DEFAULT_STATE)

    _tray = pystray.Icon(
        name  = "Silverhand",
        icon  = icon_image,
        title = "Silverhand",
        menu  = _build_menu(),
    )

    def _run():
        _tray.run()

    _tray_thread = threading.Thread(target=_run, daemon=True, name="tray")
    _tray_thread.start()


def stop():
    """Stop the tray icon cleanly."""
    global _tray
    if _tray:
        try:
            _tray.stop()
        except Exception:
            pass
        _tray = None
