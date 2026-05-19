"""
core\\nas.py -- NAS file access for Silverhand
All paths rooted at \\\\MYCLOUDEX2ULTRA\\drenin\\Silverhand\\
"""

import os

# ── Config ────────────────────────────────────────────────────────────────────
NAS_ROOT = r"\\MYCLOUDEX2ULTRA\drenin\Silverhand"

# File types we'll attempt to read as text
READABLE_EXTENSIONS = {".txt", ".md", ".log", ".json", ".csv", ".py", ".bat", ".ini", ".cfg"}

# Binary/media types we recognise but can't read
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
                     ".mp3", ".mp4", ".wav", ".flac", ".avi", ".mkv",
                     ".zip", ".rar", ".7z", ".exe", ".dll", ".pdf"}

# Max characters to pull from a file before truncating
MAX_READ_CHARS = 8000

# How many directory levels deep to search
MAX_DEPTH = 3


# ── Internal helpers ──────────────────────────────────────────────────────────

def _nas_available() -> bool:
    available = os.path.exists(NAS_ROOT)
    if not available:
        print(f"[nas] NAS not reachable at: {NAS_ROOT}")
    return available


def _resolve_path(subdir: str = "") -> str:
    return os.path.join(NAS_ROOT, subdir) if subdir else NAS_ROOT


def _walk_limited(root: str, max_depth: int):
    """os.walk capped at max_depth levels."""
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= max_depth:
            dirnames.clear()
        yield dirpath, dirnames, filenames


# ── Public API ────────────────────────────────────────────────────────────────

def list_files(subdir: str = "") -> list[str]:
    """List all files under NAS_ROOT up to MAX_DEPTH. Returns relative paths."""
    target = _resolve_path(subdir)
    print(f"[nas] listing files under: {target}")

    if not _nas_available():
        return []
    if not os.path.exists(target):
        print(f"[nas] path does not exist: {target}")
        return []

    results = []
    try:
        for dirpath, _, filenames in _walk_limited(target, MAX_DEPTH):
            for f in filenames:
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, target)
                results.append(rel)
        print(f"[nas] found {len(results)} file(s)")
    except Exception as e:
        print(f"[nas] list_files error: {e}")

    return results


def find_files(keyword: str, subdir: str = "") -> list[str]:
    """Search filenames for keyword (case-insensitive). Returns relative paths."""
    target = _resolve_path(subdir)
    print(f"[nas] find_files root: {target}")

    if not _nas_available():
        return []
    if not os.path.exists(target):
        print(f"[nas] path does not exist: {target}")
        return []

    keyword = keyword.strip().rstrip(".,!?")
    print(f"[nas] cleaned keyword: '{keyword}'")

    matches = []
    try:
        for dirpath, _, filenames in _walk_limited(target, MAX_DEPTH):
            for f in filenames:
                if keyword.lower() in f.lower():
                    full = os.path.join(dirpath, f)
                    rel = os.path.relpath(full, target)
                    matches.append(rel)
    except Exception as e:
        print(f"[nas] find_files error: {e}")

    print(f"[nas] find_files matched {len(matches)} file(s)")
    return matches


# Return codes for read_file so the caller can give a specific voice response
READ_OK          = "ok"
READ_NOT_FOUND   = "not_found"
READ_IS_BINARY   = "is_binary"
READ_NAS_DOWN    = "nas_down"
READ_ERROR       = "error"

def read_file(filename: str, subdir: str = "") -> tuple[str, str]:
    """
    Read a text file from NAS.
    Returns (status, contents_or_empty_string).
    Status is one of: READ_OK, READ_NOT_FOUND, READ_IS_BINARY, READ_NAS_DOWN, READ_ERROR.
    """
    if not _nas_available():
        return READ_NAS_DOWN, ""

    target = os.path.join(_resolve_path(subdir), filename)
    print(f"[nas] read_file path: {target}")

    if not os.path.isfile(target):
        print(f"[nas] exact path not found, attempting find...")
        matches = find_files(filename, subdir)
        if not matches:
            print(f"[nas] no matches found for: {filename}")
            return READ_NOT_FOUND, ""
        target = os.path.join(_resolve_path(subdir), matches[0])
        print(f"[nas] resolved to: {target}")

    _, ext = os.path.splitext(target)
    ext = ext.lower()

    if ext in BINARY_EXTENSIONS:
        print(f"[nas] binary file type: {ext}")
        return READ_IS_BINARY, ext

    if ext not in READABLE_EXTENSIONS:
        print(f"[nas] unsupported extension: {ext}")
        return READ_NOT_FOUND, ""

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            contents = f.read(MAX_READ_CHARS)
        if len(contents) == MAX_READ_CHARS:
            contents += "\n\n[truncated]"
        print(f"[nas] read {len(contents)} chars from {os.path.basename(target)}")
        return READ_OK, contents
    except Exception as e:
        print(f"[nas] read_file error: {e}")
        return READ_ERROR, ""
