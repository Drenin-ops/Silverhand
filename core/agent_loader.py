"""
core\agent_loader.py — Loads and validates agent.json config.

Usage:
    from core.agent_loader import cfg

    cfg.agent_name          # "Johnny"
    cfg.llm_port            # 1234
    cfg.system_prompt       # full system prompt string
    cfg.nas_memory_dir      # NAS memory path
    cfg.tts_engine          # "piper" or "rvc"
    cfg.gui_port            # 7477
    cfg.wake_phrases        # list of strings
"""

import json
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Locate agent.json — always next to main.py (project root)
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent   # D:\Silverhand
_CONFIG_PATH = _ROOT / "agent.json"


def _load() -> dict:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"agent.json not found at {_CONFIG_PATH}\n"
            f"Create one based on the template before running."
        )
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Config accessor — flat properties for easy imports
# ---------------------------------------------------------------------------

class AgentConfig:
    def __init__(self, data: dict):
        self._data = data

        # Agent identity
        agent                   = data["agent"]
        self.agent_name         = agent["name"]
        self.display_name       = agent.get("display_name", self.agent_name)
        self.wake_phrases       = agent.get("wake_phrases", [])

        # LLM
        llm                     = data["llm"]
        self.llm_port           = llm.get("port", 1234)
        self.system_prompt      = llm["system_prompt"]

        # TTS
        tts                     = data["tts"]
        self.tts_engine         = tts.get("engine", "piper")   # "piper" | "rvc"
        self.piper_exe          = tts.get("piper_exe", "")
        self.piper_model        = tts.get("piper_model", "")
        self.rvc_enabled        = tts.get("rvc_enabled", False)
        self.rvc_model          = tts.get("rvc_model", "")
        self.rvc_index          = tts.get("rvc_index", "")
        self.rvc_pitch          = tts.get("rvc_pitch", 0)

        # STT
        stt                     = data["stt"]
        self.stt_model_size     = stt.get("model_size", "base.en")
        self.stt_device         = stt.get("device", "cpu")
        self.stt_compute_type   = stt.get("compute_type", "int8")
        self.stt_sample_rate    = stt.get("sample_rate", 16000)
        self.stt_duration       = stt.get("duration", 6)
        self.stt_device_index   = stt.get("device_index", 1)

        # GUI
        gui                     = data["gui"]
        self.gui_port           = gui.get("port", 7477)
        self.gui_skin           = gui.get("skin", "ui\\agent.html")
        self.gui_open_browser   = gui.get("open_browser", True)

        # NAS
        nas                     = data["nas"]
        self.nas_root           = nas.get("root", "")
        self.nas_subdir         = nas.get("subdir", "")
        self.nas_credential_key = nas.get("credential_key", "")

        # Storage paths
        storage                 = data.get("storage", {})
        self.nas_memory_dir     = storage.get("memory_dir", "")
        self.nas_logs_dir       = storage.get("logs_dir", "")
        self.nas_models_dir     = storage.get("models_dir", "")
        self.nas_config_dir     = storage.get("config_dir", "")

        # Hotkeys
        hotkeys                 = data.get("hotkeys", {})
        self.ptt_key            = hotkeys.get("ptt_key", "`")
        self.toggle_key         = hotkeys.get("toggle_key", "pause")

    def get(self, key: str, default=None):
        """Raw dict access for any non-mapped key."""
        return self._data.get(key, default)

    def dump(self) -> str:
        """Pretty-print config for debug logging."""
        lines = [
            f"Agent:       {self.agent_name} ({self.display_name})",
            f"LLM port:    {self.llm_port}",
            f"TTS engine:  {self.tts_engine}",
            f"RVC enabled: {self.rvc_enabled}",
            f"STT model:   {self.stt_model_size} on {self.stt_device}",
            f"GUI port:    {self.gui_port}",
            f"NAS root:    {self.nas_root}",
            f"Memory dir:  {self.nas_memory_dir}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton — imported by all modules as `from core.agent_loader import cfg`
# ---------------------------------------------------------------------------

cfg = AgentConfig(_load())
