# Satellite Phase 2 — Audio Capture & Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Board captures microphone audio while a button is held and streams raw PCM chunks over WebSocket to satellite.py, which buffers them and returns a stub reply.

**Architecture:** FreeRTOS task on Core 0 reads ES8311 mic via I2S in 40ms stereo chunks, strips to mono, and queues them. The main loop (Core 1) dequeues and sends binary WebSocket frames. satellite.py accumulates binary frames per-client into a bytearray and calls `_process_audio()` on `talk_end`. A partial overlay on the board shows recording state and the reply.

**Tech Stack:** ESP32-S3 Arduino, LVGL 9.x, ESP_I2S, ES8311 ESP-IDF driver, FreeRTOS, Python asyncio websockets

---

## File Map

| File | Change |
|---|---|
| `companion/es8311.h` | Copy from `examples/15_ES8311/es8311.h` |
| `companion/es8311.c` | Copy from `examples/15_ES8311/es8311.c` |
| `companion/es8311_reg.h` | Copy from `examples/15_ES8311/es8311_reg.h` |
| `companion/companion.ino` | Add I2S/ES8311 init, capture task, UI button, overlay, reply handler |
| `core/satellite.py` | Add binary frame handling, per-client talk state, `_process_audio` stub |

---

## Task 1: Copy ES8311 Driver Files

**Files:**
- Copy: `examples/15_ES8311/es8311.h` → `companion/es8311.h`
- Copy: `examples/15_ES8311/es8311.c` → `companion/es8311.c`
- Copy: `examples/15_ES8311/es8311_reg.h` → `companion/es8311_reg.h`

- [ ] **Step 1: Copy the three driver files**

Run in PowerShell:
```powershell
$src = "C:\Users\J\OneDrive\Documents\Arduino\examples\15_ES8311"
$dst = "C:\Users\J\OneDrive\Documents\Arduino\companion"
Copy-Item "$src\es8311.h"     $dst
Copy-Item "$src\es8311.c"     $dst
Copy-Item "$src\es8311_reg.h" $dst
```

- [ ] **Step 2: Verify files exist**

```powershell
Get-ChildItem "C:\Users\J\OneDrive\Documents\Arduino\companion" | Select-Object Name
```

Expected: `companion.ino`, `es8311.h`, `es8311.c`, `es8311_reg.h`

---

## Task 2: satellite.py — Per-Client Talk State & Binary Frame Handling

**Files:**
- Modify: `D:\Silverhand\core\satellite.py`

The current `handler()` tries to `json.loads()` every message, which crashes on binary frames. We need to:
1. Route binary frames to an audio buffer
2. Handle `talk_start` by initializing a per-client buffer
3. Handle `talk_end` by processing the buffer and sending a reply
4. Remove the now-dead `handle_talk_start` function

- [ ] **Step 1: Add talk state dict and `_process_audio` stub after the existing cache globals**

In `satellite.py`, after the line `_network_ts    = 0.0`:

```python
# ─── TALK STATE ───────────────────────────────────────────────────
_talk_state: dict = {}   # websocket → {"buf": bytearray}
```

- [ ] **Step 2: Add `_process_audio` stub after `get_network()`**

Add this function before the `WEBSOCKET HANDLER` section:

```python
# ═══════════════════════════════════════════════════════════════════
#  AUDIO PROCESSING (stub — faster-whisper wires in Phase 3)
# ═══════════════════════════════════════════════════════════════════

def _process_audio(buf: bytearray) -> str:
    seconds = len(buf) / 32000  # 16kHz × 16-bit mono = 32000 bytes/s
    log.info(f"Audio received: {len(buf)} bytes ({seconds:.1f}s)")
    return "Bridge connected. STT wires in Phase 3."
```

- [ ] **Step 3: Replace the entire `handler()` function and remove `handle_talk_start`**

Delete `handle_talk_start` and replace `handler()` with:

```python
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
                _talk_state[id(websocket)] = {"buf": bytearray()}
                log.info("Talk started")

            elif cmd == "talk_end":
                state = _talk_state.pop(id(websocket), None)
                if state:
                    reply = _process_audio(state["buf"])
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
```

- [ ] **Step 4: Restart satellite and verify it starts cleanly**

```
python core\satellite.py
```

Expected: `[SAT] Silverhand bridge starting on port 8877` with no errors.

---

## Task 3: companion.ino — Includes, Pin Defines, and Audio Globals

**Files:**
- Modify: `companion/companion.ino` — top of file

- [ ] **Step 1: Add audio includes after the existing includes**

After `#include "HWCDC.h"`, add:

```cpp
#include "ESP_I2S.h"
#include "es8311.h"
```

- [ ] **Step 2: Add audio pin defines after the existing pin defines**

After `#define TP_INT     21`, add:

```cpp
#define I2S_MCK    16
#define I2S_BCK     9
#define I2S_WS     45
#define I2S_DI     10   // mic in
#define I2S_DO      8   // speaker out
#define PIN_PA     46   // power amp enable
```

- [ ] **Step 3: Add audio globals after the display/touch globals**

After `void touch_isr(void) { FT3168->IIC_Interrupt_Flag = true; }`, add:

```cpp
// ─── AUDIO ──────────────────────────────────────────────────────
#define CHUNK_BYTES   1280   // 640 mono int16 samples = 40ms at 16kHz
#define STEREO_BYTES  2560   // CHUNK_BYTES × 2 channels

I2SClass i2s;

struct AudioChunk { uint8_t data[CHUNK_BYTES]; };
static QueueHandle_t audioQ = nullptr;
static volatile bool recording = false;
```

- [ ] **Step 4: Verify the sketch still compiles (no link errors yet — functions referenced ahead are fine in Arduino)**

Open `companion.ino` in Arduino IDE, click **Verify**. Expected: compiles or fails only on missing function bodies (which we add in later tasks).

---

## Task 4: companion.ino — ES8311 Init + I2S Setup in `setup()`

**Files:**
- Modify: `companion/companion.ino`

- [ ] **Step 1: Add `es8311_codec_init()` helper function before `buildUI()`**

```cpp
static esp_err_t es8311_codec_init() {
  es8311_handle_t h = es8311_create(0, ES8311_ADDRRES_0);
  if (!h) { USBSerial.println("ES8311 create failed"); return ESP_FAIL; }
  const es8311_clock_config_t clk = {
    .mclk_inverted       = false,
    .sclk_inverted       = false,
    .mclk_from_mclk_pin  = true,
    .mclk_frequency      = 16000 * 256,
    .sample_frequency    = 16000
  };
  esp_err_t r = ESP_OK;
  r |= es8311_init(h, &clk, ES8311_RESOLUTION_16, ES8311_RESOLUTION_16);
  r |= es8311_microphone_config(h, false);
  r |= es8311_microphone_gain_set(h, (es8311_mic_gain_t)3);
  return r;
}
```

- [ ] **Step 2: Add PA pin, I2S, and ES8311 init in `setup()`, after `Wire.begin()`**

After the line `Wire.begin(IIC_SDA, IIC_SCL);`, add:

```cpp
  // Audio power + I2S
  pinMode(PIN_PA, OUTPUT);
  digitalWrite(PIN_PA, HIGH);

  i2s.setPins(I2S_BCK, I2S_WS, I2S_DO, I2S_DI, I2S_MCK);
  if (!i2s.begin(I2S_MODE_STD, 16000, I2S_DATA_BIT_WIDTH_16BIT,
                 I2S_SLOT_MODE_STEREO, I2S_STD_SLOT_BOTH)) {
    USBSerial.println("I2S init failed");
  } else {
    USBSerial.println("I2S OK");
  }

  if (es8311_codec_init() != ESP_OK) {
    USBSerial.println("ES8311 init failed");
  } else {
    USBSerial.println("ES8311 OK");
  }
```

- [ ] **Step 3: Compile and flash, check serial output**

Expected serial lines during boot:
```
I2S OK
ES8311 OK
```

If `ES8311 create failed`: check that `Wire.begin()` runs before `es8311_codec_init()` (it does, per above order).

---

## Task 5: companion.ino — FreeRTOS Capture Task

**Files:**
- Modify: `companion/companion.ino`

- [ ] **Step 1: Add `captureTask()` before `buildUI()`**

```cpp
static void captureTask(void *) {
  static uint8_t stereo_buf[STEREO_BYTES];
  AudioChunk chunk;
  while (true) {
    size_t n = i2s.readBytes((char *)stereo_buf, STEREO_BYTES);
    if (!recording || n < STEREO_BYTES) continue;
    // strip right channel — keep left (even-indexed int16 samples)
    int16_t *s = (int16_t *)stereo_buf;
    int16_t *m = (int16_t *)chunk.data;
    for (int i = 0; i < CHUNK_BYTES / 2; i++) {
      m[i] = s[i * 2];
    }
    xQueueSend(audioQ, &chunk, 0);   // drop if queue full
  }
}
```

- [ ] **Step 2: Create the queue and start the task in `setup()`, after ES8311 init**

After the ES8311 init block, add:

```cpp
  audioQ = xQueueCreate(4, sizeof(AudioChunk));
  xTaskCreatePinnedToCore(captureTask, "capture", 4096, nullptr, 1, nullptr, 0);
  USBSerial.println("Capture task OK");
```

- [ ] **Step 3: Drain the queue in `loop()` and send binary frames**

In `loop()`, before `ws.loop();`, add:

```cpp
  AudioChunk chunk;
  while (xQueueReceive(audioQ, &chunk, 0) == pdTRUE) {
    if (wsUp) ws.sendBIN(chunk.data, CHUNK_BYTES);
  }
```

- [ ] **Step 4: Compile and flash — verify no crash**

Expected: boots normally, dashboard works, no watchdog reset. The capture task runs but `recording` is false so nothing is sent.

---

## Task 6: companion.ino — UI Button and Overlay

**Files:**
- Modify: `companion/companion.ino` — `buildUI()` and widget handles section

- [ ] **Step 1: Add overlay and reply widget handles to the widget handles section**

After `lv_obj_t *netList=nullptr;`, add:

```cpp
lv_obj_t *overlay=nullptr, *lblListening=nullptr, *lblReply=nullptr;
lv_obj_t *talkBtn=nullptr;
static lv_timer_t *replyTimer=nullptr;
```

- [ ] **Step 2: Add `hide_overlay_cb` timer callback before `buildUI()`**

```cpp
static void hide_overlay_cb(lv_timer_t *t) {
  if (overlay) lv_obj_add_flag(overlay, LV_OBJ_FLAG_HIDDEN);
  replyTimer = nullptr;
}
```

- [ ] **Step 3: Add talk button event callback before `buildUI()`**

```cpp
static void talk_btn_cb(lv_event_t *e) {
  lv_event_code_t code = lv_event_get_code(e);
  if (code == LV_EVENT_PRESSED) {
    recording = true;
    ws.sendTXT("{\"cmd\":\"talk_start\"}");
    lv_label_set_text(lblListening, "\xE2\x97\x8F LISTENING");
    lv_obj_set_style_text_color(lblListening, C_CYAN, 0);
    lv_obj_clear_flag(overlay, LV_OBJ_FLAG_HIDDEN);
  } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
    recording = false;
    ws.sendTXT("{\"cmd\":\"talk_end\"}");
  }
}
```

- [ ] **Step 4: Shrink device list and add button + overlay in `buildUI()`**

Replace the device list block (from `const int DY = NY + 74;` to the end of `buildUI()`) with:

```cpp
  const int DY = NY + 74;
  mkRule(scr, DY - 4);
  lv_obj_t *td = mkLbl(scr, "DEVICES", C_MUTE, &lv_font_montserrat_12);
  lv_obj_align(td, LV_ALIGN_TOP_LEFT, 14, DY + 3);

  // device list — shorter to make room for talk button
  netList = lv_list_create(scr);
  lv_obj_set_size(netList, LCD_WIDTH - 4, LCD_HEIGHT - DY - 84);
  lv_obj_align(netList, LV_ALIGN_TOP_MID, 0, DY + 20);
  lv_obj_set_style_bg_color(netList, C_BG, 0);
  lv_obj_set_style_bg_opa(netList, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(netList, 0, 0);
  lv_obj_set_style_pad_all(netList, 2, 0);
  lv_obj_set_style_pad_row(netList, 2, 0);

  // talk button — pinned to bottom
  talkBtn = lv_btn_create(scr);
  lv_obj_set_size(talkBtn, LCD_WIDTH - 8, 52);
  lv_obj_align(talkBtn, LV_ALIGN_BOTTOM_MID, 0, -4);
  lv_obj_set_style_bg_color(talkBtn, C_DIM, 0);
  lv_obj_set_style_bg_color(talkBtn, C_MUTE, LV_STATE_PRESSED);
  lv_obj_set_style_radius(talkBtn, 6, 0);
  lv_obj_set_style_border_width(talkBtn, 0, 0);
  lv_obj_t *btnLbl = lv_label_create(talkBtn);
  lv_label_set_text(btnLbl, "HOLD TO TALK");
  lv_obj_set_style_text_color(btnLbl, C_MUTE, 0);
  lv_obj_set_style_text_font(btnLbl, &lv_font_montserrat_14, 0);
  lv_obj_center(btnLbl);
  lv_obj_add_event_cb(talkBtn, talk_btn_cb, LV_EVENT_ALL, nullptr);

  // partial overlay — covers net + device zone, hidden at rest
  const int OY = NY - 4;
  overlay = lv_obj_create(scr);
  lv_obj_set_size(overlay, LCD_WIDTH, LCD_HEIGHT - OY - 60);
  lv_obj_align(overlay, LV_ALIGN_TOP_MID, 0, OY);
  lv_obj_set_style_bg_color(overlay, C_BG, 0);
  lv_obj_set_style_bg_opa(overlay, LV_OPA_90, 0);
  lv_obj_set_style_border_width(overlay, 0, 0);
  lv_obj_set_style_radius(overlay, 0, 0);
  lv_obj_remove_flag(overlay, LV_OBJ_FLAG_SCROLLABLE);

  lblListening = lv_label_create(overlay);
  lv_label_set_text(lblListening, "\xE2\x97\x8F LISTENING");
  lv_obj_set_style_text_color(lblListening, C_CYAN, 0);
  lv_obj_set_style_text_font(lblListening, &lv_font_montserrat_14, 0);
  lv_obj_align(lblListening, LV_ALIGN_CENTER, 0, -14);

  lblReply = lv_label_create(overlay);
  lv_label_set_text(lblReply, "");
  lv_obj_set_style_text_color(lblReply, C_TEXT, 0);
  lv_obj_set_style_text_font(lblReply, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_align(lblReply, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_width(lblReply, LCD_WIDTH - 32);
  lv_obj_align(lblReply, LV_ALIGN_CENTER, 0, 16);
  lv_label_set_long_mode(lblReply, LV_LABEL_LONG_WRAP);

  lv_obj_add_flag(overlay, LV_OBJ_FLAG_HIDDEN);
```

- [ ] **Step 5: Compile and flash — verify button appears at bottom, overlay hidden**

Open serial monitor. Dashboard should load normally. The "HOLD TO TALK" button should appear at the bottom of the screen. Tapping it should show the overlay with "● LISTENING".

---

## Task 7: companion.ino — Handle Reply in `wsEvent`

**Files:**
- Modify: `companion/companion.ino` — `wsEvent()`

- [ ] **Step 1: Add reply handling to the `WStype_TEXT` case in `wsEvent()`**

Inside the `WStype_TEXT` block, after the `else if (!strcmp(t, "network"))` block, add:

```cpp
      } else if (!strcmp(t, "reply")) {
        const char *txt = doc["text"] | "";
        if (overlay && lblReply) {
          lv_label_set_text(lblListening, "");
          lv_label_set_text(lblReply, txt);
          lv_obj_clear_flag(overlay, LV_OBJ_FLAG_HIDDEN);
          if (replyTimer) lv_timer_delete(replyTimer);
          replyTimer = lv_timer_create(hide_overlay_cb, 4000, nullptr);
          lv_timer_set_repeat_count(replyTimer, 1);
        }
```

- [ ] **Step 2: Compile and flash**

Expected: no errors.

---

## Task 8: Integration Test

**Files:** none — verify only

- [ ] **Step 1: Start satellite on PC**

```
cd D:\Silverhand
venv\Scripts\activate
python core\satellite.py
```

Expected: `[SAT] server listening on 0.0.0.0:8877`

- [ ] **Step 2: Board connects — verify serial output**

Expected serial sequence:
```
expander OK
I2S OK
ES8311 OK
FT3168 OK
GFX OK
LVGL OK
Capture task OK
WiFi 10.0.0.x
READY
```

- [ ] **Step 3: Hold the talk button and watch the satellite log**

Hold for ~3 seconds. Release.

Expected satellite output:
```
[SAT] Talk started
[SAT] Audio received: ~96000 bytes (3.0s)
```

Byte count formula: 3s × 16000 Hz × 2 bytes = 96000. Tolerance ±10% is fine.

- [ ] **Step 4: Verify reply appears on board**

After release, the overlay should swap "● LISTENING" for the stub reply text:
`"Bridge connected. STT wires in Phase 3."`

After 4 seconds it should disappear.

- [ ] **Step 5: Verify dashboard resumes normally after overlay hides**

Metrics and device list should continue updating — overlay hides, normal dashboard view returns.
