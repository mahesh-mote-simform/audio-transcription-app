import logging
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.schemas import (
    TranscriptionCreateRequest,
    TranscriptionCreateResponse,
    TranscriptionStatusResponse,
    TranscriptionResultResponse
)
from app.services.chunking import SUPPORTED_EXTENSIONS, is_supported_format
from app.workers.tasks import transcribe_task
from db.repositories import (
    create_transcription,
    get_transcription,
    update_transcription,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcriptions", tags=["Transcriptions"])


# Start transcription for an audio file in blob storage or on local disk
@router.post("/", response_model=TranscriptionCreateResponse)
def create_transcription_job(
    request: TranscriptionCreateRequest,
    token_user_id: str = Depends(get_current_user)
):

    file_path = request.file_path.strip()

    logger.info(
        "Create job request from user %s: source=%s, path=%s",
        token_user_id, request.source_type, file_path
    )

    if not request.user_id.strip() or not file_path:
        logger.warning("Create job rejected: missing user_id or file_path")
        raise HTTPException(
            status_code=400,
            detail="user_id and file_path are required"
        )

    # Users can only create jobs for themselves
    if request.user_id != token_user_id:
        logger.warning(
            "Create job rejected: token user %s tried to act as %s",
            token_user_id, request.user_id
        )
        raise HTTPException(
            status_code=403,
            detail="user_id does not match the authenticated user"
        )

    # Reject unsupported formats before queueing any work
    if not is_supported_format(file_path):
        logger.warning("Create job rejected: unsupported format %s", file_path)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    if request.source_type == "local" and not os.path.isfile(file_path):
        logger.warning("Create job rejected: local file not found %s", file_path)
        raise HTTPException(
            status_code=400,
            detail="Local file not found"
        )

    job_id = str(uuid4())

    try:
        # Create transcription record in database
        create_transcription(
            job_id=job_id,
            user_id=request.user_id,
            blob_name=file_path,
            source_type=request.source_type,
            status="pending"
        )

        # Send transcription job to Celery
        transcribe_task.delay(job_id, file_path, request.source_type)

        logger.info("Job %s queued for user %s", job_id, request.user_id)

        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Transcription job created successfully"
        }

    except Exception as error:
        logger.exception("Failed to create job for user %s", request.user_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to create transcription job"
        ) from error


# Get transcription job status
@router.get("/{job_id}", response_model=TranscriptionStatusResponse)
def get_transcription_status(
    job_id: str,
    user_id: str = Depends(get_current_user)
):

    transcription = get_transcription(job_id, user_id)

    if not transcription:
        logger.info("Status check: job %s not found for user %s", job_id, user_id)
        raise HTTPException(
            status_code=404,
            detail="Transcription job not found"
        )

    logger.info("Status check: job %s is %s", job_id, transcription.status)

    return {
        "job_id": transcription.job_id,
        "status": transcription.status,
        "created_at": transcription.created_at
    }


# Get completed transcription result
@router.get("/{job_id}/result", response_model=TranscriptionResultResponse)
def get_transcription_result(
    job_id: str,
    user_id: str = Depends(get_current_user)
):

    transcription = get_transcription(job_id, user_id)

    if not transcription:
        logger.info("Result request: job %s not found for user %s", job_id, user_id)
        raise HTTPException(
            status_code=404,
            detail="Transcription job not found"
        )

    if transcription.status != "completed":
        logger.info(
            "Result request: job %s not ready (status %s)",
            job_id, transcription.status
        )
        raise HTTPException(
            status_code=409,
            detail=f"Transcription is not completed. Current status: {transcription.status}"
        )

    logger.info(
        "Result returned for job %s (%d segments)",
        job_id, len(transcription.transcript or [])
    )

    return {
        "job_id": transcription.job_id,
        "status": transcription.status,
        "transcript": transcription.transcript
    }


# Manually retry a job that failed after all automatic retries
@router.post("/{job_id}/retry", response_model=TranscriptionCreateResponse)
def retry_transcription_job(
    job_id: str,
    user_id: str = Depends(get_current_user)
):

    transcription = get_transcription(job_id, user_id)

    if not transcription:
        logger.info("Retry request: job %s not found for user %s", job_id, user_id)
        raise HTTPException(
            status_code=404,
            detail="Transcription job not found"
        )

    if transcription.status != "failed":
        logger.warning(
            "Retry rejected: job %s is %s, not failed",
            job_id, transcription.status
        )
        raise HTTPException(
            status_code=409,
            detail=f"Only failed jobs can be retried. Current status: {transcription.status}"
        )

    # Reset the job and clear the previous error before re-queueing
    update_transcription(job_id, status="pending")

    transcribe_task.delay(
        job_id,
        transcription.blob_name,
        transcription.source_type
    )

    logger.info(
        "Job %s re-queued by user %s (previous error: %s)",
        job_id, user_id, transcription.error
    )

    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Transcription job re-queued"
    }
