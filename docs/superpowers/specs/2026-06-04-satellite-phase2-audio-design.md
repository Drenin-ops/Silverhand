# Silverhand Satellite — Phase 2: Audio Capture & Streaming

**Date:** 2026-06-04  
**Status:** Approved  
**Scope:** Board-side audio capture + WebSocket streaming to bridge. Phase 3 (STT→LLM→reply) is out of scope here; a stub is wired so Phase 3 is a clean drop-in.

---

## Overview

The user holds a button on the board. While held, the ES8311 mic captures audio and streams raw PCM chunks over WebSocket to `satellite.py`. On release, the bridge receives a `talk_end` signal, assembles the buffer, and returns a placeholder reply. The board shows a partial overlay during recording and the reply text on completion.

---

## Protocol

All existing message types are preserved. Three types are added:

| Direction | Message | When |
|---|---|---|
| Board → Bridge | `{"cmd":"talk_start"}` | Finger down |
| Board → Bridge | binary WebSocket frame | Every ~40ms while held |
| Board → Bridge | `{"cmd":"talk_end"}` | Finger lifted |
| Bridge → Board | `{"type":"reply","text":"..."}` | After talk_end processed |

**Audio format:** 16kHz, 16-bit, mono PCM. ES8311 captures stereo over I2S; the capture task strips the right channel before sending. No compression.

---

## Board Side (`companion.ino`)

### Hardware Init (added to `setup()`)

- I2S pins: MCK=16, BCK=9, WS=45, DI=10(mic), DO=8(speaker), PA=46
- PA pin pulled HIGH to enable amp/mic power
- ES8311 init: 16kHz, 16-bit stereo, mic gain level 3
- I2S mode: STD, stereo, both slots

### FreeRTOS Capture Task

- Pinned to Core 0 (LVGL + WebSocket run on Core 1)
- Reads 2560 bytes per iteration (640 stereo frames = 40ms at 16kHz)
- When `volatile bool recording` is true: strips right channel → 1280-byte mono buffer → sends as binary WebSocket frame
- When false: discards read, loops immediately
- `recording` is set/cleared from LVGL callbacks (main core); declared `volatile`

### UI Changes

- Device list height reduced by 60px to make room at bottom
- `lv_btn` added: full width, 52px tall, label "HOLD TO TALK", muted color at rest
- `LV_EVENT_PRESSED`: sets `recording = true`, sends `{"cmd":"talk_start"}`, shows overlay
- `LV_EVENT_RELEASED`: sets `recording = false`, sends `{"cmd":"talk_end"}`, hides overlay, shows reply text when received

### Partial Overlay

- Semi-transparent dark panel covering the network + device list zone (lower ~55% of screen)
- Centered label: "● LISTENING" in cyan, montserrat_16
- Top bar and CPU/GPU arcs remain visible and live
- On `{"type":"reply","text":"..."}` received: overlay stays up, swaps "● LISTENING" for the reply text for 4 seconds, then hides

---

## Bridge Side (`satellite.py`)

### Per-Client Audio State

```python
_talk_state: dict[websocket, dict] = {}
# Per entry: {"recording": bool, "buf": bytearray}
```

Keyed by websocket object. Initialized on `talk_start`, cleared after reply is sent.

### Handler Changes

**`talk_start`:** Initializes state entry for this client, logs start.

**Binary frame:** If client has an active recording state, appends frame bytes to `buf`.

**`talk_end`:** Grabs complete buffer, calls `_process_audio(buf)` → gets reply text → sends `{"type":"reply","text":"..."}` → clears state.

### Audio Processing Stub

```python
def _process_audio(buf: bytearray) -> str:
    # Phase 3: faster-whisper STT drops in here
    log.info(f"Audio received: {len(buf)} bytes ({len(buf)/32000:.1f}s)")
    return "Bridge connected. STT wires in Phase 3."
```

The stub logs the duration so you can verify correct audio length during testing. Signature is fixed for Phase 3.

---

## Testing

1. Run `python core\satellite.py`
2. Flash companion.ino, open serial monitor
3. Hold the HOLD TO TALK button — serial should show I2S task sending chunks, bridge should log `Audio received: N bytes`
4. Release — board should show reply text overlay for 4 seconds
5. Verify audio duration in bridge log matches actual hold time

---

## Out of Scope

- STT (faster-whisper) — Phase 3
- LLM call — Phase 3
- Boot animation / screensaver — Phase 4
- Speaker playback of TTS reply — future
