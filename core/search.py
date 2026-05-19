"""
core/search.py — Web search for Silverhand via DuckDuckGo HTML scraping.
No API key. No account. Fully local.

Public API
----------
search(query: str) -> str | None
    Returns a plain-text summary of the top result, or None on failure.

is_search_query(text: str) -> bool
    Heuristic: returns True if the utterance looks like a web search request.

TRIGGER PHRASES (checked in main.py before LLM):
    "search for X"
    "look up X"
    "what is X" / "who is X" / "where is X" / "when is X" / "how is X"
    "google X" / "find out X"
    "latest X" / "current X" / "news on X"
"""

import re
import urllib.request
import urllib.parse
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DDGR_URL   = "https://html.duckduckgo.com/html/?q={query}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT    = 8          # seconds
MAX_CHARS  = 1200       # max snippet chars returned to LLM

# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------

_TRIGGER_PATTERNS = [
    r"\bsearch\s+for\b",
    r"\blook\s+up\b",
    r"\bgoogle\b",
    r"\bfind\s+out\b",
    r"^what\s+is\b",
    r"^who\s+is\b",
    r"^where\s+is\b",
    r"^when\s+is\b",
    r"^how\s+does\b",
    r"\blatest\b",
    r"\bcurrent\b",
    r"\bnews\s+on\b",
    r"\bnews\s+about\b",
    r"\bwhat.s\s+happening\b",
    r"\bwhat happened\b",
    r"\btell me about\b",
]

_TRIGGER_RE = re.compile(
    "|".join(_TRIGGER_PATTERNS),
    re.IGNORECASE,
)


def is_search_query(text: str) -> bool:
    """Return True if text looks like a web search request."""
    return bool(_TRIGGER_RE.search(text.strip()))


def extract_query(text: str) -> str:
    """
    Strip trigger phrases to get the raw search query.
    Falls back to the full text if no trigger found.
    """
    text = text.strip()
    # Remove leading trigger phrases
    cleaned = re.sub(
        r"^(search\s+for|look\s+up|google|find\s+out|tell\s+me\s+about)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Remove trailing filler
    cleaned = re.sub(r"\s+(please|for me|right now)\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or text


# ---------------------------------------------------------------------------
# HTML parser — extracts result snippets from DDG HTML response
# ---------------------------------------------------------------------------

class _DDGParser(HTMLParser):
    """Pull text from DDG result snippets (.result__snippet class)."""

    def __init__(self):
        super().__init__()
        self._in_snippet  = False
        self._in_title    = False
        self.snippets: list[str] = []
        self.titles:   list[str] = []
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "") or ""
        if "result__snippet" in classes:
            self._in_snippet = True
            self._buf = ""
        elif "result__a" in classes:
            self._in_title = True
            self._buf = ""

    def handle_endtag(self, tag):
        if self._in_snippet and tag == "a":
            self.snippets.append(self._buf.strip())
            self._in_snippet = False
        elif self._in_title and tag == "a":
            self.titles.append(self._buf.strip())
            self._in_title = False

    def handle_data(self, data):
        if self._in_snippet or self._in_title:
            self._buf += data


# ---------------------------------------------------------------------------
# Core search function
# ---------------------------------------------------------------------------

def search(query: str) -> str | None:
    """
    Query DuckDuckGo HTML interface and return a plain-text result block
    suitable for injection into the LLM system prompt.

    Returns None if no results found or on network error.
    """
    if not query:
        return None

    encoded = urllib.parse.quote_plus(query)
    url     = DDGR_URL.format(query=encoded)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[search] Network error: {e}")
        return None

    parser = _DDGParser()
    parser.feed(html)

    if not parser.snippets:
        return None

    # Build a compact result block
    lines = []
    for i, (title, snippet) in enumerate(
        zip(parser.titles or [""] * len(parser.snippets), parser.snippets)
    ):
        if i >= 3:          # top 3 results only
            break
        if title:
            lines.append(f"[{title}]")
        if snippet:
            lines.append(snippet)
        lines.append("")    # blank line between results

    result = "\n".join(lines).strip()
    return result[:MAX_CHARS] if result else None


# ---------------------------------------------------------------------------
# Quick CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "current time in Tokyo"
    print(f"Query: {q}")
    print(f"Is trigger: {is_search_query(q)}")
    print(f"Extracted: {extract_query(q)}")
    print("\nResult:")
    print(search(q) or "(no results)")
