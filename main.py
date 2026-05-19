"""
main.py -- Silverhand Agent Launcher
Reads all config from agent.json. Drop a different agent.json in any folder
and this same main.py runs a completely different agent.
"""

import re
import threading
from core.agent_loader import cfg
from core import trigger, llm
from core.memory import (
    load_history, save_history, save_turn,
    add_fact, list_facts, remove_fact, build_facts_block
)
from core.search import is_search_query, extract_query, search
from core.nas import list_files, find_files, read_file
from core.nas import READ_OK, READ_IS_BINARY, READ_NAS_DOWN, READ_NOT_FOUND, READ_ERROR
from audio.tts import speak
from ui import gui
from core import tray


print(f"[{cfg.display_name}] Loading config:")
print(cfg.dump())


# ── Memory trigger phrases ────────────────────────────────────────────────────

REMEMBER_PHRASES = ["remember this", "remember that", "make a note", "don't forget"]
FORGET_PHRASES   = ["forget that", "remove that fact", "delete that fact"]
LIST_PHRASES     = ["what do you remember", "list your facts", "what do you know about me"]
NAME_PHRASES     = ["my name is", "call me", "change my name to", "rename me to", "my name's"]


# ── NAS context ───────────────────────────────────────────────────────────────

_last_found: str | None = None


# ── Name extraction from facts ────────────────────────────────────────────────

def _extract_name_from_facts(facts: list[dict]) -> str | None:
    patterns = [
        r"(?:my|user'?s?)\s+name\s+is\s+([A-Za-z]+)",
        r"call\s+me\s+([A-Za-z]+)",
        r"name[:\s]+([A-Za-z]+)",
    ]
    for entry in facts:
        text = entry.get("fact", "")
        for p in patterns:
            m = re.search(p, text, re.I)
            if m:
                return m.group(1)
    return None


# ── NAS detection helpers ─────────────────────────────────────────────────────

def _is_list_command(text: str) -> bool:
    patterns = [
        r"\blist\b.{0,15}\bfiles?\b",
        r"\bwhat\b.{0,30}\bfiles?\b",
        r"\bshow\b.{0,15}\bfiles?\b",
        r"\bwhat'?s\b.{0,10}\bnas\b",
        r"\bfiles?\b.{0,10}\bnas\b",
        r"\bwhere'?s\b.{0,20}\bfiles?\b",
        r"\bhave\b.{0,10}\bfiles?\b",
        r"\bfiles?\b.{0,10}\byou\b.{0,10}\bhave\b",
    ]
    return any(re.search(p, text) for p in patterns)


def _extract_find_keyword(text: str) -> str | None:
    patterns = [
        r"(?:find\s+(?:a\s+)?file\s+(?:called|named)\s+)(.+)",
        r"(?:find\s+file\s+)(.+)",
        r"(?:can\s+you\s+find\s+)(.+)",
        r"(?:look(?:ing)?\s+for\s+)(.+)",
        r"(?:search(?:ing)?\s+for\s+)(.+)",
        r"(?:^|\s)find\s+(.+)",
    ]
    noise = re.compile(
        r'\b(please|now|for me|on the nas|on the server|the file|a file)\b', re.I
    )
    for p in patterns:
        m = re.search(p, text)
        if m:
            keyword = noise.sub('', m.group(1)).strip().rstrip(".,!?")
            if keyword:
                return keyword
    return None


def _is_open_last_command(text: str) -> bool:
    patterns = [
        r"\b(open|read|show|load)\b.{0,10}\b(it|that|the\s+file|this)\b",
        r"\b(open|read|show|load)\b\s*$",
    ]
    return any(re.search(p, text) for p in patterns)


def _extract_read_filename(text: str) -> str | None:
    patterns = [
        r"(?:read\s+file\s+)(.+)",
        r"(?:open\s+file\s+)(.+)",
        r"(?:summarize\s+(?:file\s+)?)(.+)",
        r"(?:read\s+)(.+)",
        r"(?:open\s+)(.+)",
    ]
    noise = re.compile(r'\b(please|now|for me|on the nas)\b', re.I)
    for p in patterns:
        m = re.search(p, text)
        if m:
            filename = noise.sub('', m.group(1)).strip().rstrip(".,!?")
            if filename and filename not in ("it", "that", "this", "the file"):
                return filename
    return None


# ── Speak + print + GUI ───────────────────────────────────────────────────────

def _say(text: str) -> None:
    print(f"[{cfg.agent_name}] {text}")
    gui.on_response(text)
    tray.set_state("speaking")
    if not tray.is_muted():
        speak(text)
    gui.on_idle()
    tray.set_state("idle")


# ── Tray callbacks ────────────────────────────────────────────────────────────

def _tray_toggle_mode() -> str:
    new_mode = trigger.toggle_mode()
    gui.on_mode_change(new_mode)
    return new_mode


def _tray_mute_toggle(muted: bool) -> None:
    state = "muted" if muted else "idle"
    tray.set_state(state)
    print(f"[tray] TTS {'muted' if muted else 'unmuted'}")


def _tray_exit() -> None:
    print("[tray] Exit requested via tray.")
    import os
    os._exit(0)


# ── Memory handler ────────────────────────────────────────────────────────────

def _handle_memory_command(user_input: str) -> bool:
    lowered = user_input.lower().strip()

    if any(lowered.startswith(p) for p in REMEMBER_PHRASES):
        for p in REMEMBER_PHRASES:
            if lowered.startswith(p):
                fact = user_input[len(p):].strip().lstrip(":").strip()
                break
        if fact:
            ok = add_fact(fact)
            _say("Got it. Noted." if ok else "Already have that one.")
        else:
            _say("What do you want me to remember?")
        return True

    if any(p in lowered for p in LIST_PHRASES):
        facts = list_facts()
        if not facts:
            _say("Nothing stored yet.")
        else:
            lines = [f"{e['id']}. {e['fact']}" for e in facts]
            _say("Here's what I've got: " + ". ".join(lines))
        return True

    if any(p in lowered for p in FORGET_PHRASES):
        match = re.search(r'\d+', user_input)
        if match:
            fact_id = int(match.group())
            ok = remove_fact(fact_id)
            _say(f"Fact {fact_id} removed." if ok else "No fact with that ID.")
        else:
            _say("Tell me the ID number of the fact to remove.")
        return True

    for phrase in NAME_PHRASES:
        if phrase in lowered:
            idx  = lowered.index(phrase) + len(phrase)
            name = user_input[idx:].strip().strip(".,!?").split()[0]
            if name:
                existing = list_facts()
                for entry in existing:
                    if re.search(r'\bname\b|\bcall me\b', entry["fact"], re.I):
                        remove_fact(entry["id"])
                add_fact(f"my name is {name}")
                gui.send({"type": "set_name", "name": name})
                _say(f"Got it. {name}.")
            return True

    return False


# ── NAS read helper ───────────────────────────────────────────────────────────

def _read_and_summarize(filename: str, history: list[dict], facts_block: str) -> list[dict]:
    print(f"[nas] reading file: {filename}")
    status, payload = read_file(filename)

    if status == READ_NAS_DOWN:
        _say("NAS is down. Can't reach the server right now.")
        return history

    if status == READ_IS_BINARY:
        ext = payload
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            _say(f"That's an image file. It's at memory/{filename} if you want to open it yourself.")
        elif ext in (".mp3", ".mp4", ".wav", ".flac"):
            _say("That's a media file. Can't play or read it, but it's there.")
        else:
            _say("That's a binary file. Not something I can read.")
        return history

    if status in (READ_NOT_FOUND, READ_ERROR):
        _say(f"Can't find or read '{filename}'. Check the name and try again.")
        return history

    augmented_input = (
        f"I just pulled this file from the NAS -- '{filename}'. "
        f"Here's the content:\n\n{payload}\n\n"
        f"Give me a summary of what this is."
    )
    messages = llm.build_messages(history, augmented_input, facts_block=facts_block)
    response = llm.chat(messages)
    if response:
        history.append({"role": "user",      "content": f"[NAS file: {filename}]"})
        history.append({"role": "assistant", "content": response})
        _say(response)
        save_turn(history)
    else:
        _say("Got the file but the LLM didn't respond. Try again.")

    return history


# ── NAS handler ───────────────────────────────────────────────────────────────

def _handle_nas_command(
    user_input: str,
    history: list[dict],
    facts_block: str
) -> tuple[bool, list[dict]]:
    global _last_found
    lowered = user_input.lower().strip()

    if _is_list_command(lowered):
        files = list_files()
        if not files:
            _say("NAS is either down or empty. Nothing to list.")
        else:
            summary = ", ".join(files[:10])
            if len(files) > 10:
                summary += f", and {len(files) - 10} more"
            _say(f"Found {len(files)} files: {summary}.")
        return True, history

    keyword = _extract_find_keyword(lowered)
    if keyword:
        print(f"[nas] searching for: {keyword}")
        matches = find_files(keyword)
        if not matches:
            _say(f"Nothing on the NAS matching '{keyword}'.")
            _last_found = None
        elif len(matches) == 1:
            _last_found = matches[0]
            _say(f"One match: {matches[0]}.")
        else:
            _last_found = matches[0]
            result   = ", ".join(matches[:5])
            overflow = f", and {len(matches) - 5} more" if len(matches) > 5 else ""
            _say(f"{len(matches)} matches: {result}{overflow}.")
        return True, history

    if _is_open_last_command(lowered):
        if _last_found:
            history = _read_and_summarize(_last_found, history, facts_block)
        else:
            _say("Open what? I don't have a file in mind. Try searching for one first.")
        return True, history

    filename = _extract_read_filename(lowered)
    if filename:
        _last_found = filename
        history = _read_and_summarize(filename, history, facts_block)
        return True, history

    return False, history


# ── GUI input queue ───────────────────────────────────────────────────────────

_gui_input_queue: list[str] = []

def _handle_gui_text(text: str) -> None:
    _gui_input_queue.append(text)


# ── Conversation pipeline ─────────────────────────────────────────────────────

def _run_pipeline(
    user_input: str,
    history: list[dict],
    facts_block: str
) -> tuple[list[dict], str]:

    print(f"[You] {user_input}")
    gui.on_user_input(user_input)

    if "shut yourself down" in user_input.lower():
        _say("Going dark.")
        return history, facts_block

    if _handle_memory_command(user_input):
        facts_block = build_facts_block()
        name = _extract_name_from_facts(list_facts())
        if name:
            gui.send({"type": "set_name", "name": name})
        return history, facts_block

    handled, history = _handle_nas_command(user_input, history, facts_block)
    if handled:
        return history, facts_block

    gui.on_thinking()
    tray.set_state("thinking")

    # ── Web search intercept ──────────────────────────────────────────────────
    web_context = ""
    if is_search_query(user_input):
        raw_query = extract_query(user_input)
        print(f"[search] querying: {raw_query}")
        result    = search(raw_query)
        if result:
            web_context = f"[Web search results for '{raw_query}']\n{result}"
            print(f"[search] got results ({len(result)} chars)")
        else:
            web_context = f"[Web search for '{raw_query}' returned no results]"
            print("[search] no results")

    combined_facts = facts_block
    if web_context:
        combined_facts = (facts_block + "\n\n" + web_context).strip()

    messages = llm.build_messages(history, user_input, facts_block=combined_facts)
    response = llm.chat(messages)

    if response:
        _say(response)
        history.append({"role": "user",      "content": user_input})
        history.append({"role": "assistant", "content": response})
        save_turn(history)
    else:
        tray.set_state("error")
        _say("Lost the signal. Try again.")
        tray.set_state("idle")

    return history, facts_block


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    print(f"[{cfg.display_name}] Initializing...")

    tray.start(
        on_toggle_mode = _tray_toggle_mode,
        on_mute_toggle = _tray_mute_toggle,
        on_exit        = _tray_exit,
    )
    print("[tray] Icon running in system tray.")

    def _push_name():
        name = _extract_name_from_facts(list_facts())
        if name:
            gui.send({"type": "set_name", "name": name})

    gui.start(on_text_input=_handle_gui_text, on_name_request=_push_name, open_browser=cfg.gui_open_browser)

    trigger.register_hotkeys()

    history     = load_history()
    facts_block = build_facts_block()
    if facts_block:
        print("[memory] Facts injected into system prompt.")

    gui.wait_ready(timeout=15)
    _push_name()
    name = _extract_name_from_facts(list_facts())
    print(f"[gui] Greeting as: {name}" if name else "[gui] No name in facts — defaulting to V")

    gui.on_mode_change(trigger.get_mode())

    _say("I'm here.")
    print(f"[{cfg.display_name}] Ready. Hold backtick to talk, or speak the wake phrase.")

    try:
        while True:
            if _gui_input_queue:
                user_input  = _gui_input_queue.pop(0)
                history, facts_block = _run_pipeline(user_input, history, facts_block)
                if "shut yourself down" in user_input.lower():
                    break
                continue

            gui.on_listening()
            tray.set_state("listening")
            user_input = trigger.listen()
            if not user_input:
                gui.on_idle()
                tray.set_state("idle")
                continue

            history, facts_block = _run_pipeline(user_input, history, facts_block)
            if "shut yourself down" in user_input.lower():
                break

    except KeyboardInterrupt:
        print(f"\n[{cfg.display_name}] Interrupted.")
        if not tray.is_muted():
            speak("Later.")

    finally:
        tray.stop()
        save_history(history)
        print("[memory] History saved.")


if __name__ == "__main__":
    main()
