# Silverhand Satellite — Phase 4: TTS Audio to Device Speaker

**Date:** 2026-06-04  
**Status:** Approved  
**Scope:** After the bridge returns a text reply, it also streams Piper TTS audio back to the board as binary WebSocket frames. The board plays through the ES8311 speaker via I2S. PC speaker playback is not triggered for satellite replies (board-only). RVC voice conversion is skipped for low latency (Piper-only).

---

## Overview

When the user releases the talk button, the existing pipeline runs: STT → LLM → `{"type":"reply","text":"..."}`. Phase 4 extends the bridge to also call Piper TTS, resample the output to 16kHz 16-bit mono, and stream it as binary WebSocket frames. The board buffers incoming chunks in a FreeRTOS queue and plays them from a dedicated task. The overlay stays visible for the duration of audio playback, dismissing when the queue drains after `audio_end`.

---

## Protocol

Three new message types added to the bridge→board direction. All existing message types are unchanged.

| Direction | Message | When |
|---|---|---|
| Bridge → Board | `{"type":"reply","text":"..."}` | Existing — text displayed in overlay |
| Bridge → Board | `{"type":"audio_start"}` | TTS bytes ready; board prepares playback |
| Bridge → Board | binary frame (1280 bytes) | Raw 16kHz 16-bit mono PCM, ~35ms apart |
| Bridge → Board | `{"type":"audio_end"}` | Stream complete; board drains then hides overlay |

**Chunk size:** 1280 bytes = 640 int16 mono samples = 40ms at 16kHz.  
**Send rate:** one chunk every 35ms (bridge `asyncio.sleep(0.035)`) — slightly faster than real-time to prevent board starvation while staying within the 8-item jitter buffer.  
**Audio failure fallback:** if Piper fails, bridge sends only `reply` text. Board has a 10-second safety timer started on `reply` receipt (replacing the Phase 3 4-second timer) — overlay hides eventually even with no audio.

---

## Bridge Changes

### `audio/tts.py` — new `piper_to_pcm(text: str) -> bytes | None`

Runs Piper on the prepped text, writes to a temp WAV, then pipes through ffmpeg to resample to 16kHz 16-bit mono and returns raw bytes. RVC is skipped entirely. Returns `None` on any subprocess failure; caller falls back to text-only reply.

```python
def piper_to_pcm(text: str) -> bytes | None:
    text = prep(text)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    try:
        r = subprocess.run(
            [cfg.piper_exe, "--model", cfg.piper_model, "--output_file", tmp],
            input=text.encode(), capture_output=True, timeout=30)
        if r.returncode != 0 or not os.path.getsize(tmp):
            return None
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp,
             "-ar", "16000", "-ac", "1", "-f", "s16le", "-"],
            capture_output=True, timeout=30)
        return r2.stdout if r2.returncode == 0 else None
    except Exception:
        return None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
```

### `satellite.py` — `talk_end` handler (after sending reply JSON)

`piper_to_pcm` runs in the executor so the asyncio event loop stays free for metrics pushes during TTS generation.

```python
from audio.tts import piper_to_pcm

# ... inside talk_end, after: await websocket.send(json.dumps({"type":"reply","text":reply}))

pcm = await loop.run_in_executor(None, piper_to_pcm, reply)
if pcm:
    await websocket.send(json.dumps({"type": "audio_start"}))
    CHUNK = 1280
    for i in range(0, len(pcm), CHUNK):
        await websocket.send(pcm[i:i + CHUNK])
        await asyncio.sleep(0.035)
    await websocket.send(json.dumps({"type": "audio_end"}))
```

---

## Board Changes (`companion.ino`)

### New Globals

Added alongside the existing `audioQ` / `recording` declarations:

```cpp
static QueueHandle_t playbackQ   = nullptr;
static volatile bool audioPlaying = false;   // set true on audio_start, false on audio_end
static volatile bool hideOverlay  = false;   // set by playbackTask, read by loop()
```

### `playbackTask` — Core 0, alongside `captureTask`

Reads mono `AudioChunk` structs from `playbackQ`. Duplicates each sample to L+R channels (ES8311 I2S is stereo). Writes 2560-byte stereo buffer to I2S. When the queue times out (100ms) and `audioPlaying` is false, the stream is fully drained — sets `hideOverlay = true` for `loop()` to act on from the LVGL thread.

```cpp
static void playbackTask(void *) {
    static uint8_t stereo[STEREO_BYTES];
    AudioChunk chunk;
    while (true) {
        if (xQueueReceive(playbackQ, &chunk, pdMS_TO_TICKS(100)) == pdTRUE) {
            int16_t *src = (int16_t *)chunk.data;
            int16_t *dst = (int16_t *)stereo;
            for (int i = 0; i < CHUNK_BYTES / 2; i++) {
                dst[i * 2]     = src[i];
                dst[i * 2 + 1] = src[i];
            }
            i2s.write(stereo, STEREO_BYTES);
        } else if (!audioPlaying) {
            hideOverlay = true;
        }
    }
}
```

### `setup()` additions

After the existing `audioQ` / `captureTask` lines:

```cpp
playbackQ = xQueueCreate(8, sizeof(AudioChunk));  // 8 × 40ms = 320ms jitter buffer
xTaskCreatePinnedToCore(playbackTask, "playback", 4096, nullptr, 1, nullptr, 0);
```

### `wsEvent` changes

**`WStype_BIN`:** push to `playbackQ` when `audioPlaying` is true; drop otherwise (the board never received binary frames before Phase 4, so any binary frame outside an active playback session is unexpected).

```cpp
case WStype_BIN:
    if (audioPlaying) {
        AudioChunk c;
        memcpy(c.data, payload, min((size_t)CHUNK_BYTES, len));
        xQueueSend(playbackQ, &c, 0);  // drop if full — safe under bridge rate-limiting
    }
    break;
```

**`WStype_DISCONNECTED`:** add `audioPlaying = false` so that if the connection drops mid-stream, `playbackTask` can detect queue drain and hide the overlay rather than hanging indefinitely.

**`WStype_TEXT` additions in `audio_start` / `audio_end` / `reply` branches:**

```cpp
} else if (!strcmp(t, "audio_start")) {
    audioPlaying = true;
    if (replyTimer) { lv_timer_delete(replyTimer); replyTimer = nullptr; }

} else if (!strcmp(t, "audio_end")) {
    audioPlaying = false;
    // playbackTask detects queue drain on next 100ms timeout → sets hideOverlay

} else if (!strcmp(t, "reply")) {
    // existing overlay display logic, unchanged
    // change only: 10-second fallback timer instead of 4-second
    replyTimer = lv_timer_create(hide_overlay_cb, 10000, nullptr);
    lv_timer_set_repeat_count(replyTimer, 1);
}
```

### `loop()` addition

Must run on Core 1 (the LVGL thread) — `loop()` is the right place:

```cpp
if (hideOverlay) {
    hideOverlay = false;
    if (overlay) lv_obj_add_flag(overlay, LV_OBJ_FLAG_HIDDEN);
    if (replyTimer) { lv_timer_delete(replyTimer); replyTimer = nullptr; }
}
```

### `PIN_PA` (46)

Already set `HIGH` permanently in `setup()`. No change required.

---

## Data Flow

```
talk_end received
  → _process_audio() in executor → reply string
  → send {"type":"reply","text":"..."}          ← board shows text, starts 10s fallback timer
  → piper_to_pcm(reply) in executor
      → Piper subprocess → temp WAV
      → ffmpeg: resample to 16kHz 16-bit mono → bytes
      → None on failure → skip audio (text-only)
  → send {"type":"audio_start"}                 ← board: audioPlaying=true, cancel timer
  → send binary chunks every 35ms               ← board: push to playbackQ
  → send {"type":"audio_end"}                   ← board: audioPlaying=false
                                                 ← playbackTask drains queue → hideOverlay=true
                                                 ← loop() hides overlay
```

---

## Error Handling

| Failure | Behavior |
|---|---|
| Piper subprocess fails / times out | `piper_to_pcm` returns `None`; bridge skips audio; board shows text with 10s fallback timer |
| ffmpeg fails | Same as above |
| Board `playbackQ` full (unexpected) | Chunk dropped silently; audible glitch but no crash |
| WebSocket drops mid-stream | `finally` block clears `_talk_state` on bridge; `WStype_DISCONNECTED` clears `audioPlaying` on board → playbackTask drains remaining queue then sets `hideOverlay` → overlay hides |

---

## Files Changed

| File | Change |
|---|---|
| `D:\Silverhand\audio\tts.py` | Add `piper_to_pcm(text) -> bytes \| None` |
| `D:\Silverhand\core\satellite.py` | Import `piper_to_pcm`; extend `talk_end` handler to stream audio |
| `C:\Users\J\OneDrive\Documents\Arduino\companion\companion.ino` | Add `playbackQ`, `playbackTask`, globals, `wsEvent` audio branches, `loop()` overlay check |

---

## Out of Scope

- RVC voice conversion for satellite replies — Phase 4 uses Piper-only for latency
- PC speaker playback of satellite replies — board-only by design
- Streaming TTS (chunked Piper output before full generation) — not needed; Piper is fast enough
- Boot animation / idle screensaver — future
- Persistent conversation history across reconnects — future
