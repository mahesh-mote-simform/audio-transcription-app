
import logging
import os
import time

import whisper


logger = logging.getLogger(__name__)

WHISPER_MODEL_NAME = "base"


# Load the model once when the service starts
logger.info("Loading Whisper model '%s'", WHISPER_MODEL_NAME)
_load_started = time.perf_counter()

model = whisper.load_model(
    WHISPER_MODEL_NAME,
    download_root=os.getenv("WHISPER_MODEL_DIR", "/app/models")
)

logger.info(
    "Whisper model loaded in %.1fs on %s",
    time.perf_counter() - _load_started, model.device
)


# Transcribe audio and return the complete text
def transcribe_audio(audio_file: str) -> str:

    logger.info("Transcribing %s", os.path.basename(audio_file))
    started = time.perf_counter()

    result = model.transcribe(audio_file)

    logger.info(
        "Transcribed %s in %.1fs",
        os.path.basename(audio_file), time.perf_counter() - started
    )

    return result["text"].strip()


# Transcribe audio and return text with timestamps
def transcribe_with_timestamps(audio_file: str) -> list[dict]:

    logger.info("Transcribing %s with timestamps", os.path.basename(audio_file))
    started = time.perf_counter()

    result = model.transcribe(audio_file)

    logger.info(
        "Transcribed %s in %.1fs: %d segments, language=%s",
        os.path.basename(audio_file),
        time.perf_counter() - started,
        len(result["segments"]),
        result.get("language")
    )

    return [
        {
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"].strip()
        }
        for segment in result["segments"]
    ]
