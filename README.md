# Audio Transcription API

This service takes an audio file, turns it into text with OpenAI Whisper, and gives you back a transcript with timestamps. You send a request, get a job ID right away, and check back when the job is done. Long recordings are fine. They get cut into pieces and transcribed in parallel behind the scenes.

---

## Getting it running

### What you'll need

- **Python 3.12**
- **ffmpeg** (it includes `ffprobe`). The app uses it to check and split audio files.
- **Redis**. Celery uses it as the queue between the API and the workers.
- **An Azure Storage account**, but only if you want to transcribe files kept in Blob Storage. Local files work without it.

On Ubuntu/Debian:

```bash
sudo apt install ffmpeg redis-server
```

Or run Redis in Docker if you'd rather not install it:

```bash
docker run -d --name redis -p 6379:6379 redis:7
```

### 1. Install the dependencies

```bash
cd audio-transcription-app
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Heads up: this pulls in PyTorch and the CUDA libraries, so it's a big download. Give it a few minutes.

### 2. Set up your environment

Copy the sample file and fill it in:

```bash
cp sample.env .env
```

| Variable | What it's for |
|---|---|
| `AZURE_STORAGE_CONNECTION_STRING` | Connection string for your storage account. It's required at startup, so use a placeholder if you only plan to use local files. |
| `AZURE_STORAGE_CONTAINER` | The container your audio files live in (default `audio-files`). |
| `JWT_SECRET_KEY` | A long random string used to sign and check tokens. |
| `JWT_ALGORITHM` | Leave this as `HS256`. |
| `REDIS_URL` | Where Redis is running (default `redis://localhost:6379/0`). |
| `DATABASE_PATH` | The SQLite file, relative to the project root (default `transcriptions.db`). |

There are also a few optional settings: `LOG_LEVEL` (default `INFO`), `CHUNK_DURATION_SECONDS` (default `120`) and `CHUNK_DIR` (default `audio_chunks`).

One more thing for local runs: the app looks for the Whisper model in `/app/models` (the path used inside Docker). Point it at the local `models/` folder instead:

```bash
export WHISPER_MODEL_DIR=./models
```

If `models/base.pt` isn't there, Whisper downloads it (about 140 MB) the first time it runs.

### 3. Start the worker and the API

You need two terminals, both with the virtualenv active and both opened in `audio-transcription-app/`.

**Terminal 1: the Celery worker** (this is where the transcription happens)

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

**Terminal 2: the API**

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs and you'll see the interactive Swagger UI.

### Running with Docker instead

The Dockerfile installs ffmpeg, downloads the Whisper model while it builds, and starts the worker and the API together in one container. Redis isn't included, so run it separately and make sure `REDIS_URL` points at it. On Linux, the easiest way is to share the host network:

```bash
docker build -t audio-transcription .
docker run --env-file .env --network host audio-transcription
```

---

## Trying it out

### Get a token

Every endpoint needs a JWT bearer token with a `sub` (your user ID) and an `exp` (when it expires). The API doesn't hand out tokens itself, so make one with the same secret that's in your `.env`:

```bash
python -c "
import jwt, datetime as dt
from app.core.config import settings
now = dt.datetime.now(dt.timezone.utc)
print(jwt.encode({'sub': 'user-123', 'iat': now, 'exp': now + dt.timedelta(days=1)},
                 settings.jwt_secret_key, algorithm=settings.jwt_algorithm))
"
```

`notebooks/test.ipynb` does the same thing if you'd rather use a notebook.

```bash
export TOKEN=<the token you just printed>
```

### Start a job

```bash
curl -X POST http://localhost:8000/transcriptions/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-123", "file_path": "/absolute/path/to/meeting.mp3", "source_type": "local"}'
```

To transcribe a file in Azure, set `source_type` to `"blob"` (that's the default) and give the blob name as `file_path`.

You'll get a job ID straight back:

```json
{ "job_id": "8f1c...", "status": "pending", "message": "Transcription job created successfully" }
```

### Check on it, then get the result

```bash
curl http://localhost:8000/transcriptions/<job_id> -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/transcriptions/<job_id>/result -H "Authorization: Bearer $TOKEN"
```

A finished transcript looks like this:

```json
{
  "job_id": "8f1c...",
  "status": "completed",
  "transcript": [
    { "start": 0.0, "end": 4.2, "text": "Good morning everyone, let's get started." },
    { "start": 4.2, "end": 9.8, "text": "First item on the agenda is the Q3 roadmap." }
  ]
}
```

### All the endpoints

| Method | Path | What it does |
|---|---|---|
| `POST` | `/transcriptions/` | Starts a new transcription job |
| `GET` | `/transcriptions/{job_id}` | Shows the job's status: `pending`, `processing`, `completed` or `failed` |
| `GET` | `/transcriptions/{job_id}/result` | Returns the transcript (`409` if it isn't finished yet) |
| `POST` | `/transcriptions/{job_id}/retry` | Runs a failed job again |

Supported formats: `.wav`, `.mp3`, `.flac`, `.m4a`, `.ogg`, `.aac`, `.webm`.

---

## How we built it

### The main idea: reply right away, do the work in the background

Transcribing an hour-long recording can take minutes, and an HTTP request shouldn't sit open that long. So the API does only the cheap work: it checks the token and the input, saves a row in the database, puts a task on the queue, and returns a job ID. Celery workers do the heavy lifting, and the client checks the status until the job is done.

```
 Client ──► FastAPI ──► SQLite (job row: pending)
               │
               └──► Redis queue ──► Celery worker
                                       │ download / validate / split
                                       ▼
                             ┌── chunk 1 ──┐
                             ├── chunk 2 ──┤  transcribed in parallel
                             └── chunk N ──┘
                                       │
                                       ▼
                             merge in order ──► SQLite (completed + transcript)
```

### Long audio: split it, run the pieces in parallel, stitch them back together

Running a single Whisper call on a long file is slow, and if it fails you lose the whole thing. So we:

1. **Check the file first.** We look at the extension, then ask `ffprobe` whether the file really has an audio stream. Extensions can be wrong, so we don't trust them on their own.
2. **Split it with ffmpeg** into 2-minute chunks (you can change this with `CHUNK_DURATION_SECONDS`). Each chunk is re-encoded as 16 kHz mono WAV, which is the format Whisper expects, and that also makes the cuts sample-accurate.
3. **Send out a Celery `chord`.** Each chunk is its own task, so several workers can transcribe chunks at once. When every chunk is finished, a merge task runs.
4. **Fix the timestamps.** Each chunk's timestamps start at zero, so we add the chunk's starting point to them. That starting point comes from the real length of each chunk, not just "chunk number × 120 seconds", so the last chunk (usually shorter) lines up too.
5. **Merge in order** and save the full transcript as JSON in SQLite.

### When things go wrong

We sort failures into two groups, because they need different handling:

- **Bad input** (file missing, wrong format, no audio in it) fails right away and isn't retried. Trying again would just fail the same way.
- **Temporary problems** (an Azure timeout, a worker hiccup) are retried up to 3 times, waiting a little longer each time (10s, 20s, 30s). Individual chunks retry on their own too, so one flaky chunk doesn't restart the whole job.
- If something still fails after all the retries, the job is marked `failed` with the error message, and you can start it again with the `/retry` endpoint.

A few Celery settings help make this reliable:

- `task_acks_late` and `task_reject_on_worker_lost`: if a worker crashes partway through, its task goes back on the queue instead of being lost.
- `worker_prefetch_multiplier=1`: each worker takes one long task at a time, so work spreads evenly across workers.
- Time limits (25 min soft, 30 min hard): stuck jobs get stopped. The soft limit gives the task a chance to fail cleanly first.

Temporary files (downloaded audio and the chunks) live in a folder for each job and are deleted whether the job succeeds or fails.

### Security

- Every endpoint needs a valid JWT, and tokens without `sub` or `exp` are rejected.
- You can only create jobs for yourself: the `user_id` in the request has to match the one in the token.
- Every lookup filters by both `job_id` and `user_id`, so nobody can read someone else's transcript by guessing a job ID. They just get a `404`.

### Why SQLite?

It needs no setup, and it's plenty for one machine. We turned on WAL mode so the API can read while workers write, and set a 30-second lock timeout so workers saving at the same time wait their turn instead of crashing. The table is also upgraded automatically when the app starts (for example, adding the `source_type` column to older databases). If this ever runs across several machines, Postgres would be the next step. The database code all lives in `db/repositories.py`, so the change would stay in one place.

### Why the Whisper `base` model?

It's a good trade-off between speed and accuracy, it runs on a CPU, and it uses the GPU when there is one. Each worker loads the model once when it starts, not once per task. The Docker image downloads it while building, so the first job doesn't have to wait for a download.

---

## Project layout

```
audio-transcription-app/
├── app/
│   ├── main.py              # FastAPI app; sets up the DB on startup
│   ├── api/
│   │   ├── routes.py        # The /transcriptions endpoints
│   │   ├── schemas.py       # Request/response models
│   │   └── auth.py          # JWT check
│   ├── core/
│   │   ├── config.py        # Settings, loaded from .env
│   │   └── logging_config.py
│   ├── services/
│   │   ├── chunking.py      # ffprobe validation + ffmpeg splitting
│   │   ├── storage.py       # Azure Blob upload/download
│   │   └── transcription.py # Whisper model + transcription
│   └── workers/
│       ├── celery_app.py    # Celery setup
│       └── tasks.py         # Split → parallel chunks → merge
├── db/
│   ├── database.py          # SQLite connection + schema
│   ├── repositories.py      # Create / update / get jobs
│   └── models.py            # Status names
├── notebooks/test.ipynb     # Makes a test JWT
├── models/                  # Whisper model files (not in git)
├── Dockerfile
├── requirements.txt
└── sample.env
```
