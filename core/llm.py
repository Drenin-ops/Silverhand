"""
core/llm.py
Silverhand Project - LLM Interface Module
Connects to LM Studio local API (OpenAI-compatible)
"""

import requests
import logging
from core.agent_loader import cfg

# --- Config ---
API_URL     = f"http://127.0.0.1:{cfg.llm_port}/v1/chat/completions"
MODEL_ID    = "hermes-3-llama-3.1-8b"
MAX_TOKENS  = 300
TEMPERATURE = 0.7

SYSTEM_PROMPT = cfg.system_prompt

logger = logging.getLogger(__name__)


def build_messages(history: list[dict], user_input: str, facts_block: str = "") -> list[dict]:
    """
    Build the messages list for the LLM API call.
    Injects long-term facts into the system prompt if provided.
    """
    system = SYSTEM_PROMPT
    if facts_block:
        system = system + "\n\n" + facts_block

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})
    return messages


def chat(messages: list[dict]) -> str | None:
    """
    Send conversation history to LM Studio, return the assistant reply.
    Returns the response string, or None on failure.
    """
    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
    }

    try:
        response = requests.post(API_URL, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        reply = data["choices"][0]["message"]["content"].strip()
        logger.debug(f"LLM reply: {reply}")
        return reply
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to LM Studio. Is the server running?")
        return None
    except requests.exceptions.Timeout:
        logger.error("LM Studio request timed out.")
        return None
    except Exception as e:
        logger.error(f"LLM request failed: {e}")
        return None


# --- Quick test ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    history = []
    test_input = "Hey Johnny, what do I call you?"
    print(f"Sending: {test_input}")
    msgs = build_messages(history, test_input)
    reply = chat(msgs)
    if reply:
        print(f"Silverhand: {reply}")
    else:
        print("FAILED — check that LM Studio server is running on port 1234")
