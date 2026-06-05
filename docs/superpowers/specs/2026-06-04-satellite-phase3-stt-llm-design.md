# Silverhand Satellite — Phase 3: STT + LLM Pipeline

**Date:** 2026-06-04  
**Status:** Approved  
**Scope:** Wire `_process_audio` in `satellite.py` to faster-whisper STT then Silverhand LLM. Board gets reply text. No changes to `companion.ino`, `main.py`, `stt.py`, or `llm.py`.

---

## Overview

When the user releases the talk button, the bridge has a `bytearray` of raw 16kHz 16-bit mono PCM. Phase 3 transcribes it with faster-whisper, feeds the text to the Silverhand LLM (via LM Studio), and returns the reply string to the board. History persists per WebSocket session.

---

## Data Flow

```
talk_end received
  → bytearray in _talk_state["buf"]
  → run_in_executor(_process_audio, buf, history)   ← non-blocking
      → float32 numpy (int16 / 32768.0)
      → silence check (max amplitude < 0.005)
          → return "I didn't catch that."
      → faster-whisper transcribe (beam_size=5, language="en")
      → empty result → return "I didn't catch that."
      → log "[SAT] Heard: {text}"
      → llm.build_messages(history, text)  using cfg.system_prompt, max_tokens=80
      → llm.chat(messages)
          → None (LM Studio down) → return "Lost the signal."
      → append user + assistant turns to history
      → return reply string
  → send {"type": "reply", "text": reply} to board
```

---

## Changes to `satellite.py` Only

### New Imports

```python
import numpy as np
from faster_whisper import WhisperModel
from core.stt import _get_model
from core.llm import build_messages, chat
from core.agent_loader import cfg
```

### Per-Session History in `_talk_state`

`talk_start` initializes:
```python
_talk_state[id(websocket)] = {"buf": bytearray(), "history": []}
```

`talk_end` passes history to `_process_audio`:
```python
state = _talk_state.pop(id(websocket), None)
if state:
    loop = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, _process_audio, state["buf"], state["history"])
    await websocket.send(json.dumps({"type": "reply", "text": reply}))
```

`finally` block already clears `_talk_state` on disconnect — history is discarded with it.

### `_process_audio(buf, history)` — Synchronous

```python
def _process_audio(buf: bytearray, history: list) -> str:
    seconds = len(buf) / 32000
    log.info(f"Audio received: {len(buf)} bytes ({seconds:.1f}s)")

    # Convert int16 PCM → float32
    audio = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0

    # Silence check
    if np.max(np.abs(audio)) < 0.005:
        return "I didn't catch that."

    # Transcribe
    model = _get_model()
    segments, _ = model.transcribe(audio, beam_size=5, language="en")
    text = " ".join(seg.text.strip() for seg in segments).strip()
    if not text:
        return "I didn't catch that."
    log.info(f"Heard: {text}")

    # LLM — inline HTTP call with max_tokens=80 (llm.chat() hardcodes 600)
    import requests
    messages = build_messages(history, text)
    try:
        resp = requests.post(
            f"http://127.0.0.1:{cfg.llm_port}/v1/chat/completions",
            json={"model": "hermes-3-llama-3.1-8b", "messages": messages,
                  "max_tokens": 80, "temperature": 0.75, "stream": False},
            timeout=90,
        )
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"LLM failed: {e}")
        reply = None
    if not reply:
        return "Lost the signal."

    # Update session history
    history.append({"role": "user",      "content": text})
    history.append({"role": "assistant", "content": reply})
    return reply
```

**Note:** `max_tokens=80` is applied via an inline `requests.post` call rather than `llm.chat()`, which hardcodes 600 tokens. The model ID and API URL mirror `llm.py` exactly.

---

## Error Handling

| Failure | Board sees |
|---|---|
| Audio amplitude < 0.005 | `"I didn't catch that."` |
| Whisper returns empty string | `"I didn't catch that."` |
| LLM returns None | `"Lost the signal."` |

No retries. History only appended on successful LLM reply.

---

## max_tokens Override

`llm.chat()` hardcodes `MAX_TOKENS = 600`. For the satellite, replies must fit a 368px display. `_process_audio` uses `build_messages()` for message construction but makes its own `requests.post` with `max_tokens=80`. Model ID (`hermes-3-llama-3.1-8b`) and port (`cfg.llm_port`) are shared with `llm.py` to stay in sync.

---

## Dependencies

- `numpy` — already in venv (psutil dependency chain)
- `faster_whisper` — already in venv (used by `core/stt.py`)
- `core.stt._get_model` — lazy-loads Whisper model once, thread-safe after first load
- `core.llm.build_messages` — pure function, safe to call from executor thread
- LM Studio must be running on port `cfg.llm_port`

---

## Out of Scope

- TTS playback of reply on PC speakers — Phase 4 / future
- Boot animation / idle screensaver — Phase 4
- Persistent history across board reconnects — future
- Web search intercept for satellite queries — future
