
import logging

from app.core.config import settings


LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


# Configure application logging once at startup (Celery workers configure their own)
def setup_logging():

    logging.basicConfig(
        level=settings.log_level.upper(),
        format=LOG_FORMAT
    )

    # Azure SDK logs every HTTP request at INFO, which drowns out our own logs
    logging.getLogger("azure").setLevel(logging.WARNING)
