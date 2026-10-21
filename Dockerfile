FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install audio processing dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the OpenAI Whisper base model
RUN mkdir -p /app/models && \
    python -c "import whisper; whisper.load_model('base', download_root='/app/models')"

# Copy application code
COPY app/ ./app/
COPY db/ ./db/

# Create directories for audio files and database
RUN mkdir -p /app/audio /app/data

# Set Python environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Use the downloaded model
ENV WHISPER_MODEL_DIR=/app/models

# Expose FastAPI port
EXPOSE 8000

# Start Celery worker and FastAPI
CMD ["sh", "-c", "celery -A app.workers.celery_app.celery_app worker --loglevel=info & uvicorn app.main:app --host 0.0.0.0 --port 8000"]
