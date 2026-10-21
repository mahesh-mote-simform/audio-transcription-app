
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


# Request to create a transcription job
class TranscriptionCreateRequest(BaseModel):

    user_id: str
    file_path: str
    source_type: Literal["blob", "local"] = "blob"


# Response after uploading audio
class TranscriptionCreateResponse(BaseModel):

    job_id: str
    status: str
    message: str


# Response for transcription job status
class TranscriptionStatusResponse(BaseModel):

    job_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    created_at: Optional[datetime] = None


# Single transcript segment with timestamps
class TranscriptSegment(BaseModel):

    start: float
    end: float
    text: str


# Response containing the transcription result
class TranscriptionResultResponse(BaseModel):

    job_id: str
    status: str
    transcript: list[TranscriptSegment]


# Response when an error occurs
class ErrorResponse(BaseModel):

    detail: str
