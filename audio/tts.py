"""
audio/tts.py
Jack Project - Text-to-Speech Module
Piper TTS + ffplay playback
"""

import subprocess
import tempfile
import os
import logging

# --- Config ---
PIPER_EXE    = r"D:\\Silverhand\piper\piper.exe"
VOICE_MODEL  = r"D:\\Silverhand\piper\en_US-lessac-medium.onnx"
FFPLAY_EXE   = "ffplay"

logger = logging.getLogger(__name__)


def speak(text: str) -> bool:
    if not text or not text.strip():
        logger.warning("speak() called with empty text.")
        return False

    tmp_wav = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_wav = f.name

        piper_cmd = [
            PIPER_EXE,
            "--model", VOICE_MODEL,
            "--output_file", tmp_wav,
        ]

        logger.debug(f"Running Piper: {' '.join(piper_cmd)}")
        piper_result = subprocess.run(
            piper_cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )

        if piper_result.returncode != 0:
            logger.error(f"Piper failed: {piper_result.stderr.decode('utf-8', errors='replace')}")
            return False

        if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) == 0:
            logger.error("Piper produced no output file.")
            return False

        ffplay_cmd = [
            FFPLAY_EXE,
            "-nodisp",
            "-autoexit",
            "-loglevel", "quiet",
            tmp_wav,
        ]

        logger.debug(f"Running ffplay: {' '.join(ffplay_cmd)}")
        ffplay_result = subprocess.run(
            ffplay_cmd,
            capture_output=True,
            timeout=60,
        )

        if ffplay_result.returncode != 0:
            logger.error(f"ffplay failed: {ffplay_result.stderr.decode('utf-8', errors='replace')}")
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
        if tmp_wav and os.path.exists(tmp_wav):
            try:
                os.remove(tmp_wav)
            except Exception:
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_line = "Systems online. Jack is ready."
    print(f"Speaking: {test_line}")
    success = speak(test_line)
    print("OK" if success else "FAILED — check logs above")
