
import os
import shutil
import time

from celery import chord, group
from celery.utils.log import get_task_logger

from app.core.config import settings
from app.workers.celery_app import celery_app
from app.services.chunking import InvalidAudioError, split_audio, validate_audio
from app.services.storage import download_audio
from app.services.transcription import transcribe_with_timestamps
from db.repositories import update_transcription


logger = get_task_logger(__name__)


# Working directory for a job's downloaded audio and chunks
def get_job_dir(job_id: str) -> str:

    return os.path.join(os.path.abspath(settings.chunk_dir), job_id)


# Mark a job failed, log why and remove its temporary files
def fail_job(job_id: str, error: Exception):

    logger.error("Transcription job %s failed: %s", job_id, error)

    update_transcription(
        job_id,
        status="failed",
        error=str(error)
    )

    shutil.rmtree(get_job_dir(job_id), ignore_errors=True)


# Validate and split audio, then transcribe the chunks in parallel
@celery_app.task(bind=True, max_retries=3)
def transcribe_task(
    self,
    job_id: str,
    audio_path: str,
    source_type: str = "blob"
):

    job_dir = get_job_dir(job_id)

    logger.info(
        "Job %s started (attempt %s): source=%s, path=%s",
        job_id, self.request.retries + 1, source_type, audio_path
    )

    try:
        update_transcription(job_id, status="processing")

        shutil.rmtree(job_dir, ignore_errors=True)
        os.makedirs(job_dir)

        if source_type == "local":
            source_path = audio_path

        elif source_type == "blob":
            # Keep the extension so the format can be validated after download
            extension = os.path.splitext(audio_path)[1]
            source_path = download_audio(
                audio_path,
                os.path.join(job_dir, f"source_audio{extension}")
            )

        else:
            logger.error("Job %s has unsupported source type %s", job_id, source_type)
            raise InvalidAudioError("Unsupported audio source")

        validate_audio(source_path)

        chunks = split_audio(
            source_path,
            job_dir,
            settings.chunk_duration_seconds
        )

        if source_type == "blob":
            os.remove(source_path)

        # Transcribe all chunks in parallel, then merge the results in order
        header = group(
            transcribe_chunk_task.s(chunk["path"], chunk["offset"])
            for chunk in chunks
        )
        callback = merge_chunks_task.s(job_id).on_error(
            mark_failed_task.s(job_id)
        )

        chord(header)(callback)

        logger.info(
            "Job %s dispatched %d chunks for parallel transcription",
            job_id, len(chunks)
        )

        return {"job_id": job_id, "status": "processing", "chunks": len(chunks)}

    except InvalidAudioError as error:
        # Bad input will fail the same way again, so do not retry
        logger.warning("Job %s has invalid audio, not retrying", job_id)
        fail_job(job_id, error)
        raise

    except Exception as error:

        shutil.rmtree(job_dir, ignore_errors=True)

        if self.request.retries < self.max_retries:
            logger.warning(
                "Transcription job %s failed (attempt %s), retrying: %s",
                job_id, self.request.retries + 1, error
            )
            update_transcription(job_id, status="pending")

            raise self.retry(
                exc=error,
                countdown=10 * (self.request.retries + 1)
            )

        logger.error("Job %s exhausted all %s retries", job_id, self.max_retries)
        fail_job(job_id, error)

        raise


# Transcribe one chunk and shift its timestamps to the full-audio timeline
@celery_app.task(bind=True, max_retries=3)
def transcribe_chunk_task(self, chunk_path: str, offset: float):

    # Chunk files live in the job's folder, so its name is the job ID
    job_id = os.path.basename(os.path.dirname(chunk_path))
    chunk_name = os.path.basename(chunk_path)

    logger.info(
        "Job %s: transcribing %s (offset %.1fs, attempt %s)",
        job_id, chunk_name, offset, self.request.retries + 1
    )
    started = time.perf_counter()

    try:
        segments = transcribe_with_timestamps(chunk_path)

    except Exception as error:
        logger.warning(
            "Job %s: %s failed (attempt %s), retrying: %s",
            job_id, chunk_name, self.request.retries + 1, error
        )
        raise self.retry(
            exc=error,
            countdown=10 * (self.request.retries + 1)
        )

    logger.info(
        "Job %s: %s done in %.1fs, %d segments",
        job_id, chunk_name, time.perf_counter() - started, len(segments)
    )

    return [
        {
            "start": round(segment["start"] + offset, 2),
            "end": round(segment["end"] + offset, 2),
            "text": segment["text"]
        }
        for segment in segments
        if segment["text"]
    ]


# Combine chunk transcripts (chord keeps them in chunk order) and save
@celery_app.task
def merge_chunks_task(chunk_results: list[list[dict]], job_id: str):

    logger.info("Job %s: merging %d chunk results", job_id, len(chunk_results))

    transcript = [
        segment
        for chunk_segments in chunk_results
        for segment in chunk_segments
    ]

    update_transcription(
        job_id,
        status="completed",
        transcript=transcript
    )

    shutil.rmtree(get_job_dir(job_id), ignore_errors=True)

    logger.info(
        "Job %s completed: %d segments, %.1fs of audio",
        job_id, len(transcript), transcript[-1]["end"] if transcript else 0.0
    )

    return {"job_id": job_id, "status": "completed"}


# Mark the job failed when any chunk fails after all retries
@celery_app.task
def mark_failed_task(request, exc, traceback, job_id: str):

    logger.error("Job %s: a chunk failed after all retries", job_id)
    fail_job(job_id, exc)
