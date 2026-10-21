
from celery import Celery

from app.core.config import settings

redis_url = settings.redis_url

# Create Celery application
celery_app = Celery(
    "audio_transcription",
    broker=redis_url,
    backend=redis_url,
    include=["app.workers.tasks"]
)


# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,

    # Acknowledge only after the task finishes, so a crashed worker's task is re-queued
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Transcription tasks are long, so take one at a time to spread work evenly
    worker_prefetch_multiplier=1,

    # Stop stuck tasks; the soft limit raises inside the task so it can retry or fail cleanly
    task_soft_time_limit=1500,
    task_time_limit=1800
)
