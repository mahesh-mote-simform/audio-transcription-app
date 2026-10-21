
import logging
import os
from uuid import uuid4
from azure.storage.blob import BlobServiceClient

from app.core.config import settings


logger = logging.getLogger(__name__)


# Create Azure Blob Storage client
def get_blob_service_client():

    if not settings.azure_storage_connection_string:
        logger.error("Azure Storage connection string is not configured")
        return None

    try:
        return BlobServiceClient.from_connection_string(
            settings.azure_storage_connection_string
        )
    except Exception:
        logger.exception("Failed to create Azure Blob Storage client")
        return None


# Upload audio file and return the blob name
def upload_audio(file, filename: str) -> str | None:

    blob_service_client = get_blob_service_client()

    if blob_service_client is None:
        return None

    try:
        blob_name = f"{uuid4()}_{os.path.basename(filename)}"

        blob_client = blob_service_client.get_blob_client(
            container=settings.azure_storage_container,
            blob=blob_name
        )

        blob_client.upload_blob(file, overwrite=False)

        logger.info("Uploaded audio to blob %s", blob_name)

        return blob_name

    except Exception:
        logger.exception("Failed to upload audio %s", filename)
        return None


# Download audio file for transcription
def download_audio(blob_name: str, destination_path: str) -> str:

    blob_service_client = get_blob_service_client()

    if blob_service_client is None:
        raise RuntimeError("Azure Blob Storage is unavailable")

    logger.info(
        "Downloading blob %s from container %s",
        blob_name, settings.azure_storage_container
    )

    blob_client = blob_service_client.get_blob_client(
        container=settings.azure_storage_container,
        blob=blob_name
    )

    with open(destination_path, "wb") as audio_file:
        audio_file.write(blob_client.download_blob().readall())

    logger.info(
        "Downloaded blob %s (%.1f MB)",
        blob_name, os.path.getsize(destination_path) / (1024 * 1024)
    )

    return destination_path
