
from pydantic_settings import BaseSettings, SettingsConfigDict


# Application configuration
class Settings(BaseSettings):

    # Azure Blob Storage
    azure_storage_connection_string: str
    azure_storage_container: str = "audio-files"

    # JWT authentication
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"

    # Redis and Celery
    redis_url: str = "redis://localhost:6379/0"

    # SQLite database
    database_path: str = "transcriptions.db"

    # Logging
    log_level: str = "INFO"

    # Long audio chunking
    chunk_duration_seconds: int = 120
    chunk_dir: str = "audio_chunks"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Load settings once
settings = Settings()
