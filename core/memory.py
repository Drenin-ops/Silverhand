"""
core\memory.py — Silverhand Phase 4
Two-tier memory system:
  - Short-term: rolling conversation history (all sessions, capped at MAX_MESSAGES)
  - Long-term:  persistent facts that never get dropped, injected into every session

Storage root: \\MYCLOUDEX2ULTRA\drenin\Silverhand\memory\
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

MEMORY_DIR   = Path(r"\\MYCLOUDEX2ULTRA\drenin\Silverhand\memory")
HISTORY_FILE = MEMORY_DIR / "history.json"
FACTS_FILE   = MEMORY_DIR / "facts.json"

# Rotating safety saves — cycles through slots 1–5, one written per turn
ROTATE_SLOTS = 5
ROTATE_PREFIX = "history_slot_"

# Hard cap on stored messages across all sessions combined
# Oldest messages are dropped first when exceeded
MAX_MESSAGES = 2000

# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_dir():
    """Create memory directory on NAS if it doesn't exist."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> list | dict | None:
    """Safely read a JSON file. Returns None on any failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: Path, data: list | dict) -> bool:
    """Safely write JSON to a file. Returns True on success."""
    try:
        _ensure_dir()
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)  # atomic rename
        return True
    except Exception as e:
        print(f"[memory] Write failed for {path.name}: {e}")
        return False

# ── Rotation state (in-memory counter, resets each run) ──────────────────────

_rotate_index = 0


def _next_slot_path() -> Path:
    global _rotate_index
    _rotate_index = (_rotate_index % ROTATE_SLOTS) + 1
    return MEMORY_DIR / f"{ROTATE_PREFIX}{_rotate_index}.json"

# ── Short-term: conversation history ─────────────────────────────────────────

def load_history() -> list[dict]:
    """
    Load conversation history from primary file.
    Falls back to the most recently modified rotation slot if primary is corrupt/missing.
    Returns an empty list if nothing can be loaded.
    """
    _ensure_dir()

    data = _read_json(HISTORY_FILE)
    if isinstance(data, list):
        print(f"[memory] Loaded {len(data)} messages from history.")
        return data

    # Primary failed — try rotation slots
    print("[memory] Primary history missing or corrupt. Checking rotation slots...")
    slots = sorted(
        MEMORY_DIR.glob(f"{ROTATE_PREFIX}*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    for slot in slots:
        data = _read_json(slot)
        if isinstance(data, list) and data:
            print(f"[memory] Recovered {len(data)} messages from {slot.name}.")
            return data

    print("[memory] No history found. Starting fresh.")
    return []


def save_history(history: list[dict], rotate: bool = False) -> bool:
    """
    Save conversation history to disk.
    - rotate=False (default): writes to primary history.json
    - rotate=True: writes to the next rotation slot (call each turn)

    Enforces MAX_MESSAGES cap — trims oldest messages first.
    """
    if len(history) > MAX_MESSAGES:
        history = history[-MAX_MESSAGES:]

    target = _next_slot_path() if rotate else HISTORY_FILE
    return _write_json(target, history)


def save_turn(history: list[dict]):
    """
    Convenience function — call this after every turn.
    Writes one rotating safety save. Primary is written on clean exit via save_history().
    """
    save_history(history, rotate=True)

# ── Long-term: persistent facts ───────────────────────────────────────────────

def load_facts() -> dict:
    """
    Load the long-term facts dictionary.
    Returns empty dict if none exist yet.

    Structure:
    {
      "entries": [
        {"id": 1, "fact": "User's name is J.", "added": "2026-05-19T10:00:00"},
        ...
      ]
    }
    """
    _ensure_dir()
    data = _read_json(FACTS_FILE)
    if isinstance(data, dict) and "entries" in data:
        return data
    return {"entries": []}


def add_fact(fact_text: str) -> bool:
    """
    Add a new fact to long-term memory.
    Called when user says 'remember this' or similar.
    Returns True on success.
    """
    facts = load_facts()
    existing = [e["fact"].lower() for e in facts["entries"]]

    if fact_text.lower() in existing:
        print("[memory] Fact already stored.")
        return False

    next_id = max((e["id"] for e in facts["entries"]), default=0) + 1
    facts["entries"].append({
        "id": next_id,
        "fact": fact_text,
        "added": datetime.now().isoformat(timespec="seconds")
    })
    ok = _write_json(FACTS_FILE, facts)
    if ok:
        print(f"[memory] Fact #{next_id} stored: {fact_text}")
    return ok


def remove_fact(fact_id: int) -> bool:
    """
    Remove a fact by its ID.
    Returns True if found and removed.
    """
    facts = load_facts()
    before = len(facts["entries"])
    facts["entries"] = [e for e in facts["entries"] if e["id"] != fact_id]
    if len(facts["entries"]) == before:
        print(f"[memory] Fact #{fact_id} not found.")
        return False
    ok = _write_json(FACTS_FILE, facts)
    if ok:
        print(f"[memory] Fact #{fact_id} removed.")
    return ok


def list_facts() -> list[dict]:
    """Return all stored facts as a list."""
    return load_facts()["entries"]


def build_facts_block() -> str:
    """
    Build a formatted string of all facts for injection into the system prompt.
    Returns empty string if no facts exist.
    """
    entries = list_facts()
    if not entries:
        return ""
    lines = ["Persistent facts about the user (always apply these):"]
    for e in entries:
        lines.append(f"- {e['fact']}")
    return "\n".join(lines)
