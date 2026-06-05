"""
audio/tts.py
Silverhand — Text-to-Speech Module
Piper TTS → optional RVC voice conversion → ffplay
"""

import subprocess
import tempfile
import os
import logging
from audio.tts_prep import prep

from core.agent_loader import cfg

logger = logging.getLogger(__name__)


# ── RVC inference via CLI ─────────────────────────────────────────────────────

RVC_PYTHON  = r"D:\RVC\venv\Scripts\python.exe"
RVC_INFER   = r"D:\RVC\tools\infer_cli.py"


def _rvc_convert(input_wav: str, output_wav: str) -> bool:
    """Run RVC CLI inference: input_wav → output_wav using model from cfg."""
    cmd = [
        RVC_PYTHON, RVC_INFER,
        "--f0up_key",    str(cfg.rvc_pitch),
        "--input_path",  input_wav,
        "--index_path",  cfg.rvc_index or "",
        "--f0method",    "rmvpe",
        "--opt_path",    output_wav,
        "--model_name",  os.path.basename(cfg.rvc_model),
        "--index_rate",  "0.75" if cfg.rvc_index else "0",
        "--device",      "cuda:0",
        "--is_half",     "False",
        "--filter_radius","7",
        "--resample_sr", "0",
        "--rms_mix_rate", "0.25",
        "--protect",     "0.45",
    ]
    logger.debug(f"RVC cmd: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60, cwd=r"D:\RVC")
        if result.returncode != 0:
            logger.error(f"RVC failed: {result.stderr.decode('utf-8', errors='replace')}")
            return False
        if not os.path.exists(output_wav) or os.path.getsize(output_wav) == 0:
            logger.error("RVC produced no output file.")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("RVC timed out.")
        return False
    except FileNotFoundError as e:
        logger.error(f"RVC executable not found: {e}")
        return False


# ── Core speak() ─────────────────────────────────────────────────────────────

def speak(text: str) -> bool:
    if not text or not text.strip():
        logger.warning("speak() called with empty text.")
        return False

    tmp_piper  = None
    tmp_rvc    = None
    play_file  = None

    try:
        # Step 1: Piper → WAV
        text = prep(text)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_piper = f.name

        piper_cmd = [
            cfg.piper_exe,
            "--model", cfg.piper_model,
            "--output_file", tmp_piper,
        ]
        logger.debug(f"Piper: {' '.join(piper_cmd)}")
        r = subprocess.run(piper_cmd, input=text.encode("utf-8"),
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            logger.error(f"Piper failed: {r.stderr.decode('utf-8', errors='replace')}")
            return False
        if not os.path.exists(tmp_piper) or os.path.getsize(tmp_piper) == 0:
            logger.error("Piper produced no output.")
            return False

        play_file = tmp_piper  # default: play Piper output directly

        # Step 2: RVC conversion (if enabled)
        if cfg.rvc_enabled:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_rvc = f.name
            ok = _rvc_convert(tmp_piper, tmp_rvc)
            if ok:
                play_file = tmp_rvc
                logger.debug("RVC conversion succeeded — playing converted audio.")
            else:
                logger.warning("RVC failed — falling back to Piper audio.")
                # play_file stays as tmp_piper (graceful fallback)

        # Step 3: ffplay
        ffplay_cmd = [
            "ffplay", "-nodisp", "-autoexit",
            "-loglevel", "quiet",
            play_file,
        ]
        logger.debug(f"ffplay: {' '.join(ffplay_cmd)}")
        r2 = subprocess.run(ffplay_cmd, capture_output=True, timeout=60)
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_line = "Systems online. Johnny Silverhand is ready."
    print(f"Speaking: {test_line}")
    success = speak(test_line)
    print("OK" if success else "FAILED — check logs above")
