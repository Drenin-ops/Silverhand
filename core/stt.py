"""
core/stt.py
Jack Project - Speech-to-Text Module
faster-whisper for local offline transcription
"""

import sounddevice as sd
import numpy as np
import logging
from faster_whisper import WhisperModel

# --- Config ---
MODEL_SIZE   = "base.en"       # fast and accurate for English; upgrade to "small.en" if needed
DEVICE       = "cpu"           # use "cpu" if GPU causes issues
COMPUTE_TYPE = "int8"          # float16 for GPU; use "int8" for CPU
SAMPLE_RATE  = 16000           # whisper expects 16kHz
CHANNELS     = 1               # mono
DURATION     = 6               # seconds to record per listen() call
DEVICE_INDEX = 1               # Logi USB Headset — change if mic changes

logger = logging.getLogger(__name__)

# Load model once at import time
_model = None

def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        logger.info(f"Loading Whisper model: {MODEL_SIZE} on {DEVICE}")
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
        logger.info("Whisper model loaded.")
    return _model


def listen() -> str | None:
    """
    Record audio from the default microphone for DURATION seconds,
    then transcribe it with faster-whisper.
    Returns the transcribed string, or None if nothing was detected.
    """
    logger.debug(f"Recording {DURATION}s of audio at {SAMPLE_RATE}Hz...")

    try:
        audio = sd.rec(
            int(DURATION * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            device=DEVICE_INDEX,
        )
        sd.wait()  # block until recording is done
    except Exception as e:
        logger.error(f"Microphone recording failed: {e}")
        return None

    # Flatten to 1D numpy array (whisper expects this)
    audio_flat = audio.flatten()

    # Skip if audio is basically silence
    if np.max(np.abs(audio_flat)) < 0.005:
        logger.debug("Audio too quiet — skipping transcription.")
        return None

    try:
        model = _get_model()
        segments, info = model.transcribe(
            audio_flat,
            beam_size=5,
            language="en",
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if text:
            logger.debug(f"Transcribed: {text}")
            return text
        else:
            logger.debug("Transcription returned empty result.")
            return None
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return None


# --- Quick test ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Speak now... (recording for 6 seconds)")
    result = listen()
    if result:
        print(f"You said: {result}")
    else:
        print("Nothing detected.")
