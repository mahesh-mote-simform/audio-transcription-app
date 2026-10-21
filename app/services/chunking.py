
import glob
import logging
import os
import subprocess
import time


logger = logging.getLogger(__name__)


# Formats accepted for transcription (all are normalised to 16 kHz mono WAV)
SUPPORTED_EXTENSIONS = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".webm")


# Raised for bad input that retrying will not fix
class InvalidAudioError(ValueError):
    pass


# Check the file name has a supported audio extension
def is_supported_format(filename: str) -> bool:

    return filename.lower().endswith(SUPPORTED_EXTENSIONS)


# Make sure the file exists, has a supported format and contains an audio stream
def validate_audio(audio_path: str) -> str:

    logger.info("Validating audio %s", os.path.basename(audio_path))

    if not os.path.isfile(audio_path):
        logger.warning("Audio file not found: %s", audio_path)
        raise InvalidAudioError("Audio file not found")

    if not is_supported_format(audio_path):
        logger.warning("Unsupported audio format: %s", os.path.basename(audio_path))
        raise InvalidAudioError(
            f"Unsupported audio format. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    # Extension alone can lie, so confirm ffprobe can actually read an audio stream
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            audio_path
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0 or "audio" not in result.stdout:
        logger.warning(
            "No readable audio stream in %s: %s",
            os.path.basename(audio_path), result.stderr.strip()[-200:]
        )
        raise InvalidAudioError("File is not a readable audio file")

    logger.info("Audio %s is valid", os.path.basename(audio_path))

    return audio_path


# Get audio duration in seconds using ffprobe
def get_audio_duration(audio_path: str) -> float:

    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        logger.error("ffprobe failed for %s: %s", audio_path, result.stderr.strip()[-200:])
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()[-500:]}")

    return float(result.stdout.strip())


# Split audio into fixed-length chunks and return their paths and start offsets
def split_audio(audio_path: str, output_dir: str, chunk_seconds: int) -> list[dict]:

    output_pattern = os.path.join(output_dir, "chunk_%04d.wav")

    logger.info(
        "Splitting %s into %ss chunks",
        os.path.basename(audio_path), chunk_seconds
    )
    started = time.perf_counter()

    # Re-encode to 16 kHz mono WAV so cuts are sample-accurate and Whisper-ready
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y",
            "-i", audio_path,
            "-f", "segment",
            "-segment_time", str(chunk_seconds),
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            output_pattern
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        logger.error("ffmpeg failed for %s: %s", audio_path, result.stderr.strip()[-200:])
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-500:]}")

    chunk_paths = sorted(glob.glob(os.path.join(output_dir, "chunk_*.wav")))

    if not chunk_paths:
        logger.error("ffmpeg produced no chunks for %s", audio_path)
        raise RuntimeError("Audio could not be split into chunks")

    # Use real chunk durations so offsets stay accurate for the last chunk too
    chunks = []
    offset = 0.0

    for chunk_path in chunk_paths:
        chunks.append({"path": chunk_path, "offset": offset})
        offset += get_audio_duration(chunk_path)

    logger.info(
        "Split %s into %d chunks (total %.1fs of audio) in %.1fs",
        os.path.basename(audio_path), len(chunks), offset,
        time.perf_counter() - started
    )

    return chunks
