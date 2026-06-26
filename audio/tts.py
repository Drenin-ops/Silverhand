"""
audio/tts.py
Silverhand — Text-to-Speech Module
Piper TTS → optional RVC voice conversion → ffplay / PCM bytes
"""

import subprocess
import tempfile
import os
import json
import threading
import logging
from audio.tts_prep import prep

from core.agent_loader import cfg

logger = logging.getLogger(__name__)


# ── RVC persistent server ─────────────────────────────────────────────────────

RVC_PYTHON = r"D:\RVC\venv\Scripts\python.exe"
RVC_SERVER = r"D:\RVC\tools\infer_server.py"

_rvc_proc: subprocess.Popen | None = None
_rvc_lock = threading.Lock()


def _get_rvc_proc() -> "subprocess.Popen | None":
    """Return running RVC server process, starting one if needed. Caller holds _rvc_lock."""
    global _rvc_proc
    if _rvc_proc is not None and _rvc_proc.poll() is None:
        return _rvc_proc

    init = {
        "model_name": os.path.basename(cfg.rvc_model),
        "device":     "cuda:0",
        "is_half":    True,
    }
    try:
        _rvc_proc = subprocess.Popen(
            [RVC_PYTHON, RVC_SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=r"D:\RVC",
            text=True,
            bufsize=1,
        )
        _rvc_proc.stdin.write(json.dumps(init) + "\n")
        _rvc_proc.stdin.flush()

        ready = _rvc_proc.stdout.readline().strip()
        if ready != "ready":
            logger.error(f"RVC server failed to start (got: {ready!r})")
            _rvc_proc.kill()
            _rvc_proc = None
            return None
        logger.info("RVC server ready — model loaded in process")
        return _rvc_proc
    except Exception as e:
        logger.error(f"RVC server start failed: {e}")
        _rvc_proc = None
        return None


def warmup_rvc() -> None:
    """Pre-load RVC model in background so first real call has no startup delay."""
    if not cfg.rvc_enabled:
        return
    def _warm():
        with _rvc_lock:
            _get_rvc_proc()
    threading.Thread(target=_warm, name="rvc-warmup", daemon=True).start()
    logger.info("RVC warm-up started in background")


def _rvc_convert(input_wav: str, output_wav: str) -> bool:
    """Send one inference job to the persistent RVC server process."""
    with _rvc_lock:
        proc = _get_rvc_proc()
        if proc is None:
            return False

        job = {
            "input_path":   input_wav,
            "f0up_key":     cfg.rvc_pitch,
            "f0method":     "rmvpe",
            "index_path":   cfg.rvc_index or "",
            "opt_path":     output_wav,
            "index_rate":   0.75 if cfg.rvc_index else 0.0,
            "filter_radius": 3,
            "resample_sr":  0,
            "rms_mix_rate": 0.25,
            "protect":      0.45,
        }
        try:
            proc.stdin.write(json.dumps(job) + "\n")
            proc.stdin.flush()
            result = proc.stdout.readline().strip()
            if result == "ok":
                return os.path.exists(output_wav) and os.path.getsize(output_wav) > 0
            logger.error(f"RVC job error: {result}")
            return False
        except Exception as e:
            logger.error(f"RVC IPC error: {e}")
            try:
                proc.kill()
            except Exception:
                pass
            global _rvc_proc
            _rvc_proc = None
            return False


# ── Core speak() — plays on PC speakers via ffplay ────────────────────────────

def speak(text: str) -> bool:
    if not text or not text.strip():
        logger.warning("speak() called with empty text.")
        return False

    tmp_piper = None
    tmp_rvc   = None
    play_file = None

    try:
        text = prep(text)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_piper = f.name

        r = subprocess.run(
            [cfg.piper_exe, "--model", cfg.piper_model, "--output_file", tmp_piper],
            input=text.encode("utf-8"), capture_output=True, timeout=30)
        if r.returncode != 0:
            logger.error(f"Piper failed: {r.stderr.decode('utf-8', errors='replace')}")
            return False
        if not os.path.exists(tmp_piper) or os.path.getsize(tmp_piper) == 0:
            logger.error("Piper produced no output.")
            return False

        play_file = tmp_piper

        if cfg.rvc_enabled:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_rvc = f.name
            if _rvc_convert(tmp_piper, tmp_rvc):
                play_file = tmp_rvc
            else:
                logger.warning("RVC failed — falling back to Piper audio.")

        r2 = subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", play_file],
            capture_output=True, timeout=120)
        if r2.returncode != 0:
            logger.error(f"ffplay failed: {r2.stderr.decode('utf-8', errors='replace')}")
            return False

        return True

    except subprocess.TimeoutExpired:
        logger.error("TTS timed out.")
        return False
    except FileNotFoundError as e:
        logger.error(f"Executable not found: {e}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected TTS error: {e}")
        return False
    finally:
        for f in (tmp_piper, tmp_rvc):
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass


# ── piper_to_pcm() — returns raw 16kHz 16-bit mono PCM for WebSocket streaming ─

def piper_to_pcm(text: str) -> bytes | None:
    text = prep(text)
    tmp_piper = None
    tmp_rvc   = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_piper = f.name
        r = subprocess.run(
            [cfg.piper_exe, "--model", cfg.piper_model, "--output_file", tmp_piper],
            input=text.encode(), capture_output=True, timeout=30)
        if r.returncode != 0 or not os.path.getsize(tmp_piper):
            return None
        play_file = tmp_piper
        if cfg.rvc_enabled:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_rvc = f.name
            if _rvc_convert(tmp_piper, tmp_rvc):
                play_file = tmp_rvc
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-i", play_file,
             "-ar", "16000", "-ac", "1", "-f", "s16le", "-"],
            capture_output=True, timeout=90)
        return r2.stdout if r2.returncode == 0 else None
    except Exception:
        return None
    finally:
        for f in (tmp_piper, tmp_rvc):
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_line = "Systems online. Johnny Silverhand is ready."
    print(f"Speaking: {test_line}")
    success = speak(test_line)
    print("OK" if success else "FAILED — check logs above")
