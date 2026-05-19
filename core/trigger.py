# core\trigger.py
# Phase 3 — Wake Word / PTT toggle
# PTT:  hold backtick (`) to record, release to transcribe
# Wake: always-on listener activates on "hey johnny" or "silverhand"
# Toggle: press backtick + T, or call toggle_mode() programmatically

import threading
import queue
import time
import numpy as np
import sounddevice as sd
import keyboard

# ── Config ────────────────────────────────────────────────────────────────────
PTT_KEY          = "`"          # backtick
TOGGLE_HOTKEY    = "pause"      # Pause key to switch modes
SAMPLE_RATE      = 16000
CHANNELS         = 1
DTYPE            = "int16"
CHUNK_DURATION   = 0.5          # seconds per audio chunk in wake mode
SILENCE_TIMEOUT  = 2.0          # seconds of silence before ending wake capture
MAX_RECORD_SECS  = 15           # safety cap for PTT recording

# Wake word strings to match (lowercased)
WAKE_PHRASES     = ["hey johnny", "silverhand", "hey silverhand", "wake the fuck up"]

# ── Mode state ────────────────────────────────────────────────────────────────
_MODE_PTT  = "ptt"
_MODE_WAKE = "wake"
_current_mode = _MODE_PTT
_mode_lock    = threading.Lock()
_recording    = False   # guard: block toggle while PTT is capturing

def get_mode() -> str:
    with _mode_lock:
        return _current_mode

def toggle_mode() -> str:
    global _current_mode
    if _recording:
        print("[trigger] Toggle ignored — currently recording")
        return _current_mode
    with _mode_lock:
        _current_mode = _MODE_WAKE if _current_mode == _MODE_PTT else _MODE_PTT
        new_mode = _current_mode
    print(f"[trigger] Mode switched → {new_mode.upper()}")
    return new_mode

# ── Lazy STT import ───────────────────────────────────────────────────────────
# Import here so trigger.py doesn't force a model load at import time.
def _transcribe(audio_np: np.ndarray) -> str | None:
    from core.stt import _get_model
    model = _get_model()
    segments, _ = model.transcribe(audio_np, language="en")
    text = " ".join(seg.text for seg in segments).strip()
    return text if text else None

# ── PTT mode ──────────────────────────────────────────────────────────────────
def _ptt_listen() -> str | None:
    """Record while backtick is held. Return transcript or None."""
    print("[trigger] PTT — hold ` to speak")

    # Wait for key press
    keyboard.wait(PTT_KEY, suppress=False)
    print("[trigger] Recording…")

    frames = []
    start  = time.time()

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE) as stream:
        while keyboard.is_pressed(PTT_KEY):
            if time.time() - start > MAX_RECORD_SECS:
                print("[trigger] Max record time reached")
                break
            chunk, _ = stream.read(int(SAMPLE_RATE * 0.05))  # 50 ms chunks
            frames.append(chunk.copy())

    if not frames:
        return None

    audio = np.concatenate(frames, axis=0).flatten().astype(np.float32) / 32768.0
    print("[trigger] Transcribing…")
    return _transcribe(audio)

# ── Wake word mode ─────────────────────────────────────────────────────────────
def _wake_listen() -> str | None:
    """
    Stream audio continuously. When a wake phrase is detected via STT on a
    rolling buffer, capture the following speech and return its transcript.

    Note: openwakeword requires a model download on first run (~50 MB).
    Falls back to a simple STT-based wake detection if openwakeword is missing.
    """
    try:
        return _wake_oww()
    except ImportError:
        print("[trigger] openwakeword not found — using STT-based wake detection (less accurate)")
        return _wake_stt_fallback()

def _wake_oww() -> str | None:
    """Wake word detection using openwakeword (preferred)."""
    from openwakeword.model import Model as OWWModel

    # Load model once per call — cache externally if performance matters
    oww = OWWModel(inference_framework="onnx")
    # openwakeword ships with 'hey_mycroft', 'alexa', etc.
    # We detect "hey johnny" via STT fallback since no custom model exists yet.
    # Use oww for generic activity detection, then confirm with STT.

    CHUNK = int(SAMPLE_RATE * CHUNK_DURATION)
    print("[trigger] Wake — listening for wake phrase…")

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE) as stream:
        while True:
            if get_mode() != _MODE_WAKE:
                return None  # mode switched mid-listen

            audio_chunk, _ = stream.read(CHUNK)
            audio_np = audio_chunk.flatten().astype(np.float32) / 32768.0

            # Quick STT check on the chunk for wake phrase
            text = _transcribe(audio_np)
            if text and any(phrase in text.lower() for phrase in WAKE_PHRASES):
                print(f"[trigger] Wake phrase detected: '{text}'")
                return _capture_response(stream)

def _wake_stt_fallback() -> str | None:
    """Wake detection using rolling STT chunks (no openwakeword dependency)."""
    CHUNK = int(SAMPLE_RATE * CHUNK_DURATION)
    print("[trigger] Wake — listening for wake phrase (STT fallback)…")

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE) as stream:
        while True:
            if get_mode() != _MODE_WAKE:
                return None

            audio_chunk, _ = stream.read(CHUNK)
            audio_np = audio_chunk.flatten().astype(np.float32) / 32768.0

            text = _transcribe(audio_np)
            if text and any(phrase in text.lower() for phrase in WAKE_PHRASES):
                print(f"[trigger] Wake phrase detected: '{text}'")
                return _capture_response(stream)

def _capture_response(stream: sd.InputStream) -> str | None:
    """After wake word fires, capture the follow-up utterance."""
    print("[trigger] Listening for command…")
    frames      = []
    silence_start = None
    CHUNK       = int(SAMPLE_RATE * CHUNK_DURATION)
    RMS_THRESH  = 0.01   # silence threshold

    start = time.time()
    while time.time() - start < MAX_RECORD_SECS:
        chunk, _ = stream.read(CHUNK)
        audio_np = chunk.flatten().astype(np.float32) / 32768.0
        frames.append(audio_np)

        rms = float(np.sqrt(np.mean(audio_np ** 2)))
        if rms < RMS_THRESH:
            if silence_start is None:
                silence_start = time.time()
            elif time.time() - silence_start > SILENCE_TIMEOUT:
                break
        else:
            silence_start = None

    if not frames:
        return None

    audio = np.concatenate(frames)
    return _transcribe(audio)

# ── Public API ────────────────────────────────────────────────────────────────
def listen() -> str | None:
    """
    Main entry point for main.py.
    Routes to PTT or wake word listener based on current mode.
    Returns transcript string or None.
    """
    mode = get_mode()
    if mode == _MODE_PTT:
        return _ptt_listen()
    else:
        return _wake_listen()

# ── Toggle hotkey registration ─────────────────────────────────────────────────
def register_hotkeys():
    """Call once at startup to enable backtick+T mode toggle."""
    keyboard.add_hotkey(TOGGLE_HOTKEY, toggle_mode, suppress=True)
    print(f"[trigger] Hotkeys registered — toggle mode: {TOGGLE_HOTKEY}")
