import logging
import os
import sqlite3
from contextlib import contextmanager

from app.core.config import settings


# Resolve the database path from the project root so the API and workers share one file
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_PATH = os.path.join(PROJECT_ROOT, settings.database_path)

logger = logging.getLogger(__name__)


# Open a database connection and always close it
@contextmanager
def get_db_connection():

    # Wait up to 30s for a lock instead of failing when workers write at the same time
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row

    try:
        yield connection
    except sqlite3.Error:
        logger.exception("Database error on %s", DATABASE_PATH)
        raise
    finally:
        connection.close()


# Create transcription table
def init_db():

    with get_db_connection() as connection:

        # WAL lets readers and a writer work at the same time
        connection.execute("PRAGMA journal_mode=WAL")

        connection.execute("""
            CREATE TABLE IF NOT EXISTS transcriptions (
                job_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                blob_name TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'blob',
                status TEXT NOT NULL,
                transcript TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Add source_type to databases created before it existed
        columns = [
            row["name"]
            for row in connection.execute("PRAGMA table_info(transcriptions)")
        ]

        if "source_type" not in columns:
            logger.info("Migrating database: adding source_type column")
            connection.execute("""
                ALTER TABLE transcriptions
                ADD COLUMN source_type TEXT NOT NULL DEFAULT 'blob'
            """)

        connection.commit()

    logger.info("Database ready at %s", DATABASE_PATH)
