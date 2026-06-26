# Phase 4: TTS Audio to Device Speaker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream Piper TTS audio from the Python bridge to the ESP32-S3 board speaker after every voice reply, with the overlay dismissing when playback completes.

**Architecture:** Bridge adds `piper_to_pcm()` to `audio/tts.py` (Piper → ffmpeg resample → raw bytes), then `satellite.py` streams those bytes as binary WebSocket frames bracketed by `audio_start`/`audio_end` JSON messages. Board side adds a FreeRTOS `playbackTask` on Core 0 that reads a `playbackQ`, duplicates mono→stereo, and writes to I2S; `loop()` hides the overlay when signalled by the task.

**Tech Stack:** Python asyncio + websockets + subprocess (Piper, ffmpeg) on bridge; Arduino C++ FreeRTOS + ESP32 I2SClass + WebSocketsClient on board.

---

## File Map

| File | Change |
|---|---|
| `D:\Silverhand\audio\tts.py` | Add `piper_to_pcm(text) -> bytes \| None` |
| `D:\Silverhand\core\satellite.py` | Add `from audio.tts import piper_to_pcm`; extend `talk_end` handler |
| `D:\Silverhand\tests\test_tts_pcm.py` | New — pytest unit tests for `piper_to_pcm` |
| `C:\Users\J\OneDrive\Documents\Arduino\companion\companion.ino` | Add globals, `playbackTask`, setup lines, wsEvent branches, loop check |

---

## Task 1: Install pytest and write failing tests for `piper_to_pcm`

**Files:**
- Create: `D:\Silverhand\tests\__init__.py`
- Create: `D:\Silverhand\tests\test_tts_pcm.py`

- [ ] **Step 1: Install pytest into the venv**

```powershell
& "D:\Silverhand\venv\Scripts\pip.exe" install pytest
```

Expected output: `Successfully installed pytest-...`

- [ ] **Step 2: Create the tests package**

Create `D:\Silverhand\tests\__init__.py` as an empty file.

- [ ] **Step 3: Write the failing tests**

Create `D:\Silverhand\tests\test_tts_pcm.py`:

```python
from unittest.mock import patch, MagicMock


def test_returns_bytes_on_success():
    fake_pcm = b"\x01\x00" * 800

    with patch("audio.tts.prep", return_value="hello"), \
         patch("audio.tts.cfg") as mock_cfg, \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("subprocess.run") as mock_run, \
         patch("os.path.getsize", return_value=100), \
         patch("os.path.exists", return_value=True), \
         patch("os.remove"):
        mock_cfg.piper_exe = "piper"
        mock_cfg.piper_model = "model.onnx"
        mock_ntf.return_value.__enter__.return_value.name = "/tmp/fake.wav"
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout=fake_pcm),
        ]
        from audio.tts import piper_to_pcm
        assert piper_to_pcm("hello") == fake_pcm


def test_returns_none_when_piper_fails():
    with patch("audio.tts.prep", return_value="hello"), \
         patch("audio.tts.cfg"), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("subprocess.run") as mock_run, \
         patch("os.path.getsize", return_value=0), \
         patch("os.path.exists", return_value=True), \
         patch("os.remove"):
        mock_ntf.return_value.__enter__.return_value.name = "/tmp/fake.wav"
        mock_run.return_value = MagicMock(returncode=1)
        from audio.tts import piper_to_pcm
        assert piper_to_pcm("hello") is None


def test_returns_none_when_ffmpeg_fails():
    with patch("audio.tts.prep", return_value="hello"), \
         patch("audio.tts.cfg"), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("subprocess.run") as mock_run, \
         patch("os.path.getsize", return_value=100), \
         patch("os.path.exists", return_value=True), \
         patch("os.remove"):
        mock_ntf.return_value.__enter__.return_value.name = "/tmp/fake.wav"
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1),
        ]
        from audio.tts import piper_to_pcm
        assert piper_to_pcm("hello") is None


def test_returns_none_when_piper_executable_missing():
    with patch("audio.tts.prep", return_value="hello"), \
         patch("audio.tts.cfg"), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("subprocess.run", side_effect=FileNotFoundError("piper not found")), \
         patch("os.path.exists", return_value=True), \
         patch("os.remove"):
        mock_ntf.return_value.__enter__.return_value.name = "/tmp/fake.wav"
        from audio.tts import piper_to_pcm
        assert piper_to_pcm("hello") is None
```

- [ ] **Step 4: Run tests — expect 4 failures (ImportError: cannot import `piper_to_pcm`)**

```powershell
Set-Location D:\Silverhand
& "D:\Silverhand\venv\Scripts\pytest.exe" tests/test_tts_pcm.py -v
```

Expected: 4 errors — `ImportError: cannot import name 'piper_to_pcm' from 'audio.tts'`

---

## Task 2: Implement `piper_to_pcm` in `audio/tts.py`

**Files:**
- Modify: `D:\Silverhand\audio\tts.py`

- [ ] **Step 1: Add `piper_to_pcm` at the bottom of `audio/tts.py`, before `if __name__ == "__main__":`**

The function uses `subprocess`, `tempfile`, `os` (all already imported at the top of the file) and `prep` / `cfg` (also already imported). No new imports needed.

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

- [ ] **Step 2: Run tests — expect 4 passing**

```powershell
Set-Location D:\Silverhand
& "D:\Silverhand\venv\Scripts\pytest.exe" tests/test_tts_pcm.py -v
```

Expected:
```
tests/test_tts_pcm.py::test_returns_bytes_on_success PASSED
tests/test_tts_pcm.py::test_returns_none_when_piper_fails PASSED
tests/test_tts_pcm.py::test_returns_none_when_ffmpeg_fails PASSED
tests/test_tts_pcm.py::test_returns_none_when_piper_executable_missing PASSED
4 passed
```

- [ ] **Step 3: Commit**

```powershell
Set-Location D:\Silverhand
git add audio/tts.py tests/test_tts_pcm.py tests/__init__.py
git commit -m "feat: add piper_to_pcm() — raw 16kHz PCM bytes from Piper TTS"
```

---

## Task 3: Wire `satellite.py` to stream TTS audio after reply

**Files:**
- Modify: `D:\Silverhand\core\satellite.py`

- [ ] **Step 1: Add the import at the top of `satellite.py`**

After the existing `from core.agent_loader import cfg` line, add:

```python
from audio.tts import piper_to_pcm
```

- [ ] **Step 2: Extend the `talk_end` handler**

Find this block in the `talk_end` branch of `handler()` (currently around line 308–316):

```python
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
```

Replace with:

```python
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
                    pcm = await loop.run_in_executor(None, piper_to_pcm, reply)
                    if pcm:
                        await websocket.send(json.dumps({"type": "audio_start"}))
                        CHUNK = 1280
                        for i in range(0, len(pcm), CHUNK):
                            await websocket.send(pcm[i:i + CHUNK])
                            await asyncio.sleep(0.035)
                        await websocket.send(json.dumps({"type": "audio_end"}))
                        log.info(f"Audio streamed: {len(pcm)} bytes")
```

- [ ] **Step 3: Smoke-test the bridge starts without import errors**

```powershell
Set-Location D:\Silverhand
& "D:\Silverhand\venv\Scripts\python.exe" -c "from core.satellite import handler; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 4: Commit**

```powershell
Set-Location D:\Silverhand
git add core/satellite.py
git commit -m "feat: stream Piper TTS audio to board after reply"
```

---

## Task 4: Board — add globals, `playbackTask`, and setup() lines

**Files:**
- Modify: `C:\Users\J\OneDrive\Documents\Arduino\companion\companion.ino`

Arduino has no automated unit tests. Each step ends with a compile check using Arduino IDE (Sketch → Verify/Compile, Ctrl+R). The board is not flashed until Task 6.

- [ ] **Step 1: Add three new globals after the existing `recording` line**

Find (around line 86–87):
```cpp
static QueueHandle_t audioQ = nullptr;
static volatile bool recording = false;
```

Add immediately after `recording = false;`:
```cpp
static QueueHandle_t playbackQ    = nullptr;
static volatile bool audioPlaying = false;
static volatile bool hideOverlay  = false;
```

- [ ] **Step 2: Add `playbackTask` after the closing brace of `captureTask`**

Find the closing `}` of `captureTask` (around line 255). Add the new function immediately after it:

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

- [ ] **Step 3: Add queue creation and task spawn to `setup()`**

Find these two lines in `setup()` (around line 546–547):
```cpp
  audioQ = xQueueCreate(4, sizeof(AudioChunk));
  xTaskCreatePinnedToCore(captureTask, "capture", 4096, nullptr, 1, nullptr, 0);
```

Add immediately after them:
```cpp
  playbackQ = xQueueCreate(8, sizeof(AudioChunk));
  xTaskCreatePinnedToCore(playbackTask, "playback", 4096, nullptr, 1, nullptr, 0);
  USBSerial.println("Playback task OK");
```

- [ ] **Step 4: Compile — expect zero errors**

In Arduino IDE: Sketch → Verify/Compile (Ctrl+R).  
Expected: `Compilation complete.` with no errors. Warnings about unused variables are acceptable.

---

## Task 5: Board — update `wsEvent` (all branches)

**Files:**
- Modify: `C:\Users\J\OneDrive\Documents\Arduino\companion\companion.ino`

- [ ] **Step 1: Add `audioPlaying = false` to `WStype_DISCONNECTED`**

Find (around line 477):
```cpp
    case WStype_DISCONNECTED:
      wsUp = false;
      if (lblDot) { lv_label_set_text(lblDot, "\xE2\x97\x8F OFFLINE"); lv_obj_set_style_text_color(lblDot, C_RED, 0); }
      break;
```

Replace with:
```cpp
    case WStype_DISCONNECTED:
      wsUp = false;
      audioPlaying = false;
      if (lblDot) { lv_label_set_text(lblDot, "\xE2\x97\x8F OFFLINE"); lv_obj_set_style_text_color(lblDot, C_RED, 0); }
      break;
```

- [ ] **Step 2: Add `WStype_BIN` case before `default: break;`**

Find `default: break;` at the end of the `wsEvent` switch (around line 518). Add before it:

```cpp
    case WStype_BIN:
      if (audioPlaying) {
        AudioChunk c;
        memcpy(c.data, payload, min((size_t)CHUNK_BYTES, len));
        xQueueSend(playbackQ, &c, 0);
      }
      break;
```

- [ ] **Step 3: Update the `reply` branch timer and add `audio_start` / `audio_end` branches**

Find the full `reply` branch inside `WStype_TEXT` (around line 504–513):
```cpp
      } else if (!strcmp(t, "reply")) {
        const char *txt = doc["text"] | "";
        if (overlay && lblReply && lblListening) {
          lv_label_set_text(lblListening, "");
          lv_label_set_text(lblReply, txt);
          lv_obj_clear_flag(overlay, LV_OBJ_FLAG_HIDDEN);
          if (replyTimer) lv_timer_delete(replyTimer);
          replyTimer = lv_timer_create(hide_overlay_cb, 4000, nullptr);
          lv_timer_set_repeat_count(replyTimer, 1);
        }
      }
```

Replace with:
```cpp
      } else if (!strcmp(t, "reply")) {
        const char *txt = doc["text"] | "";
        if (overlay && lblReply && lblListening) {
          lv_label_set_text(lblListening, "");
          lv_label_set_text(lblReply, txt);
          lv_obj_clear_flag(overlay, LV_OBJ_FLAG_HIDDEN);
          if (replyTimer) lv_timer_delete(replyTimer);
          replyTimer = lv_timer_create(hide_overlay_cb, 10000, nullptr);
          lv_timer_set_repeat_count(replyTimer, 1);
        }
      } else if (!strcmp(t, "audio_start")) {
        audioPlaying = true;
        if (replyTimer) { lv_timer_delete(replyTimer); replyTimer = nullptr; }
      } else if (!strcmp(t, "audio_end")) {
        audioPlaying = false;
      }
```

- [ ] **Step 4: Compile — expect zero errors**

In Arduino IDE: Sketch → Verify/Compile (Ctrl+R).  
Expected: `Compilation complete.`

---

## Task 6: Board — add `hideOverlay` check to `loop()` and flash

**Files:**
- Modify: `C:\Users\J\OneDrive\Documents\Arduino\companion\companion.ino`

- [ ] **Step 1: Add the `hideOverlay` check at the top of `loop()`**

Find the opening of `loop()` (around line 618):
```cpp
void loop() {
  AudioChunk chunk;
  while (xQueueReceive(audioQ, &chunk, 0) == pdTRUE) {
```

Add before `AudioChunk chunk;`:
```cpp
void loop() {
  if (hideOverlay) {
    hideOverlay = false;
    if (overlay) lv_obj_add_flag(overlay, LV_OBJ_FLAG_HIDDEN);
    if (replyTimer) { lv_timer_delete(replyTimer); replyTimer = nullptr; }
  }

  AudioChunk chunk;
  while (xQueueReceive(audioQ, &chunk, 0) == pdTRUE) {
```

- [ ] **Step 2: Compile — expect zero errors**

In Arduino IDE: Sketch → Verify/Compile (Ctrl+R).  
Expected: `Compilation complete.`

- [ ] **Step 3: Flash the board**

In Arduino IDE: Sketch → Upload (Ctrl+U). Wait for `Done uploading.`

Open Serial Monitor (Ctrl+Shift+M), baud rate 115200. Expected boot output:
```
I2S OK
ES8311 OK
Capture task OK
Playback task OK
expander OK
FT3168 OK
GFX OK
LVGL OK
WiFi <IP address>
READY
```

Confirm `Playback task OK` appears — this verifies `playbackQ` and `playbackTask` initialized correctly.

---

## Task 7: End-to-end test

No code changes — verification only.

- [ ] **Step 1: Start the bridge**

Double-click "Satellite Bridge" on the desktop (runs `D:\Silverhand\start_satellite.bat`). Confirm bridge log shows:
```
[SAT] Silverhand bridge starting on port 8877
```

- [ ] **Step 2: Verify board connects**

Serial monitor should show nothing new (WebSocket connects silently). Board display dot should change from `CONNECTING` → `LIVE` (green).

- [ ] **Step 3: Test voice reply with audio**

Hold the HOLD TO TALK button on the board. Say a short phrase (e.g. "What time is it?"). Release.

Bridge log should show:
```
[SAT] Talk started
[SAT] Audio received: NNNN bytes (N.Ns)
[SAT] Heard: What time is it?
[SAT] Audio streamed: NNNN bytes
```

Board behaviour:
1. Overlay shows "● LISTENING" while held
2. On release: overlay shows the reply text
3. A moment later: speaker plays the reply in Piper voice
4. Overlay hides when audio finishes (not on a fixed timer)

- [ ] **Step 4: Test fallback (Piper unavailable)**

Temporarily rename `cfg.piper_exe` path in the bridge (e.g., edit `start_satellite.bat` or the config) to a bad path. Hold → release button. Bridge should log a failure from `piper_to_pcm` and skip the audio stream. Board should show reply text and hide overlay after the 10-second fallback timer.

Restore the correct piper path when done.

- [ ] **Step 5: Test disconnect mid-stream**

While audio is playing, pull the board's USB power briefly to force a disconnect. Reconnect. Verify the board boots cleanly and the overlay is not stuck.
