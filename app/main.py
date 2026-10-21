
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.core.logging_config import setup_logging

setup_logging()

from app.api.routes import router  
from db.database import init_db  


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("Starting Audio Transcription API")
    init_db()
    logger.info("Database initialised")
    yield
    logger.info("Shutting down Audio Transcription API")


app = FastAPI(
    title="Audio Transcription API",
    lifespan=lifespan
)

app.include_router(router)

