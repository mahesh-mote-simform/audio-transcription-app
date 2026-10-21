
import json
import logging
from datetime import datetime, timezone

from db.database import get_db_connection


logger = logging.getLogger(__name__)


# Get current UTC timestamp
def get_current_time():

    return datetime.now(timezone.utc).isoformat()


# Create transcription record
def create_transcription(
    job_id: str,
    user_id: str,
    blob_name: str,
    source_type: str = "blob",
    status: str = "pending"
):

    current_time = get_current_time()

    with get_db_connection() as connection:

        connection.execute("""
            INSERT INTO transcriptions (
                job_id, user_id, blob_name, source_type, status,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id,
            user_id,
            blob_name,
            source_type,
            status,
            current_time,
            current_time
        ))

        connection.commit()

    logger.info("DB: created job %s for user %s", job_id, user_id)


# Update transcription status and result
def update_transcription(
    job_id: str,
    status: str,
    transcript=None,
    error=None
):

    current_time = get_current_time()

    if transcript is not None:
        transcript = json.dumps(transcript)

    with get_db_connection() as connection:

        cursor = connection.execute("""
            UPDATE transcriptions
            SET status = ?,
                transcript = COALESCE(?, transcript),
                error = ?,
                updated_at = ?
            WHERE job_id = ?
        """, (
            status,
            transcript,
            error,
            current_time,
            job_id
        ))

        connection.commit()

    if cursor.rowcount == 0:
        logger.warning("DB: no job %s to update to %s", job_id, status)
    else:
        logger.info("DB: job %s -> %s", job_id, status)


# Get transcription record for a specific user
def get_transcription(job_id: str, user_id: str):

    with get_db_connection() as connection:

        row = connection.execute("""
            SELECT *
            FROM transcriptions
            WHERE job_id = ? AND user_id = ?
        """, (job_id, user_id)).fetchone()

    if row is None:
        return None

    transcription = dict(row)

    if transcription["transcript"]:
        transcription["transcript"] = json.loads(
            transcription["transcript"]
        )

    return type("Transcription", (), transcription)()
