# Bulk Certificate Generator API

Backend service for the AEREO SDE Intern assignment. One request accepts a batch
of recipients, validates the entire batch, creates a generation job, renders one
PDF certificate per recipient in the background, and exposes job progress plus
certificate metadata and downloads.

## Features

- `POST /api/v1/jobs` — accepts multiple recipients, validates the whole batch,
  persists a job with one certificate row per recipient, returns **202** with a
  job UUID.
- Background processing via FastAPI `BackgroundTasks`; each certificate is
  generated in isolation, so one failure never stops the rest of the batch.
- Accurate job/certificate statuses, counts, timestamps, and `progress` (0.0–1.0).
- Job status + progress, paginated certificate listing (with status filter),
  certificate metadata, and PDF download endpoints.
- Health endpoint with a database connectivity check.
- Alembic migrations, Docker Compose, and a Pytest suite covering every required
  scenario.

## Tech Stack

Python · FastAPI · PostgreSQL · SQLAlchemy 2.x · Alembic · Pydantic ·
ReportLab · Pytest/HTTPX · Docker Compose

## Architecture

```
HTTP request
   │
   ▼
app/api/routes/        routes, status codes, response shaping (no business logic)
   │
   ▼
app/schemas/           Pydantic request/response validation
   │
   ▼
app/services/          job_service (lifecycle/queries), pdf_service (ReportLab),
   │                   storage (internal file paths)
   ▼
app/models/            SQLAlchemy 2.x ORM models (UUID primary keys)

app/workers/job_processor.py
   └── runs in-process after the 202 response: fresh DB session per job,
       one short transaction per certificate, PDF rendered outside any
       transaction.
```

### Project structure

```
app/
├── main.py                  # app factory, routers, safe global error handler
├── config.py                # pydantic-settings (DATABASE_URL, MAX_BATCH_SIZE, ...)
├── db.py                    # engine, session factory, get_db dependency
├── models/                  # Job, Certificate + status enums
├── schemas/                 # Pydantic request/response models
├── services/                # job_service, pdf_service, storage
├── workers/job_processor.py # background loop with per-recipient isolation
└── api/routes/              # jobs.py, certificates.py, health.py
templates/certificate_layout.py   # the single predefined certificate template
alembic/                     # migrations
tests/                       # pytest suite
docker/                      # DB init scripts
```

## Database model

**jobs** — `id (UUID PK)`, `status`, `total_count`, `processed_count`,
`succeeded_count`, `failed_count`, `created_at`, `started_at`, `finished_at`.

**certificates** — `id (UUID PK)`, `job_id (FK → jobs, CASCADE)`,
`recipient_name`, `email`, `status`, `error_code` (sanitized),
`file_size_bytes`, `created_at`, `generated_at`.

**Job lifecycle**

```
pending → processing → completed             (processed == total, failed == 0)
                      → completed_with_errors (processed == total, failed > 0)
                      → failed               (loop-level crash only)
```

**Certificate lifecycle:** `pending → processing → succeeded | failed`

**Progress:** `progress = processed_count / total_count`. Counters are only ever
incremented after a certificate reaches a terminal state, in the same
transaction that persists that state.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/jobs` | Create a job → `202 {job_id, status, total_count}` |
| `GET` | `/api/v1/jobs/{job_id}` | Status, counts, `progress`, timestamps |
| `GET` | `/api/v1/jobs/{job_id}/certificates` | Paginated results (`page`, `page_size`, `status`) |
| `GET` | `/api/v1/certificates/{certificate_id}` | Metadata (never includes file paths) |
| `GET` | `/api/v1/certificates/{certificate_id}/download` | PDF (`409` if not ready) |
| `GET` | `/health` | Liveness + DB check |

Interactive docs at `/docs` when the server is running.

### Validation rules

- `recipients`: 1–`MAX_BATCH_SIZE` (default **100**) entries.
- `name`: non-blank after trimming, max 100 characters.
- `email`: valid email address; duplicates within one batch are rejected.
- `certificate_title` (optional): rendered as the certificate heading; 1–100
  characters, defaults to `CERTIFICATE OF ACHIEVEMENT`.
- `event_name` (optional): rendered in the recognition sentence; 1–150
  characters, defaults to `the program`.
- The **entire** batch is validated before anything is written: a `422` leaves
  no partial job or certificate rows.

### Examples

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{
        "certificate_title": "CERTIFICATE OF ACHIEVEMENT",
        "event_name": "the Robotics Bootcamp 2026",
        "recipients":[
          {"name":"Alice Smith","email":"alice@example.com"},
          {"name":"Bob Jones","email":"bob@example.com"}
        ]}'
# 202 {"job_id":"...","status":"pending","total_count":2}

curl http://localhost:8000/api/v1/jobs/<job_id>
# {"status":"completed","total_count":2,"processed_count":2,
#  "succeeded_count":2,"failed_count":0,"progress":1.0,...}

curl "http://localhost:8000/api/v1/jobs/<job_id>/certificates?page=1&page_size=50"
curl http://localhost:8000/api/v1/certificates/<certificate_id>
curl -OJ http://localhost:8000/api/v1/certificates/<certificate_id>/download
```

## Getting started

Prerequisites: Docker + Docker Compose, Python 3.11+.

```bash
# 1. Start PostgreSQL (also creates the certgen_test database)
docker compose up -d db

# 2. Virtual environment + dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configuration
cp .env.example .env

# 4. Apply migrations
alembic upgrade head

# 5. Run the API
uvicorn app.main:app --reload
```

Run everything in containers instead:

```bash
docker compose up --build   # API on http://localhost:8000, DB on 5432
```

## Testing

The suite expects the Compose database to be running (it uses the
`certgen_test` database created by `docker/initdb`, and a temporary storage
directory — your real data is untouched).

```bash
pytest
```

Coverage of assignment scenarios:

| Requirement | Tests |
|---|---|
| Job creation (202, UUID, records persisted) | `tests/test_job_creation.py` |
| Input validation (batch limits, emails, duplicates, blanks, types) | `tests/test_validation.py` |
| Status/progress/timestamps accuracy | `tests/test_progress_and_status.py` |
| Individual failure isolation + sanitized errors | `tests/test_failure_isolation.py` |
| Certificate listing, pagination, filters | `tests/test_certificate_listing.py` |
| Metadata, downloads, path/traceback leakage checks | `tests/test_certificate_metadata_and_download.py` |
| Health endpoint | `tests/test_health.py` |

Migrations are exercised by the test session fixture (it runs
`alembic upgrade head` against `certgen_test`).

## Design notes

- **Sessions:** request handlers use the `get_db` dependency; the background
  worker opens a *fresh* session per job and closes it when the job ends.
- **Transactions:** each certificate is committed in its own short transaction
  (status update → render → final update). No transaction is held open while
  ReportLab renders a PDF, and a failed render is rolled back before the
  certificate is marked `failed` — a certificate can never be `succeeded`
  without a fully written PDF on disk (writes are atomic via temp file +
  `os.replace`).
- **Failure isolation:** each recipient is wrapped in `try/except`; failures are
  logged server-side with full detail, while clients only ever see the
  sanitized `error_code: GENERATION_FAILED`.
- **Paths:** storage paths are computed in one place
  (`app/services/storage.py`) and are never serialized into responses.

## Limitations of the in-process background tasks

This implementation deliberately uses FastAPI `BackgroundTasks` (no Redis or
Celery) to stay within assignment scope. Be aware:

1. **Not durable across restarts.** Jobs live in the database, but the queue
   lives in process memory. If the application restarts mid-job, remaining
   certificates stay `pending` and the job is never completed (a crash of the
   loop marks it `failed`). There is no retry or resume mechanism.
2. **Single process only.** Jobs are processed by the instance that accepted
   them; running replicas behind a load balancer gives no shared queue or
   cross-replica visibility of in-flight work.
3. **Competes with request handling.** PDF rendering is CPU-bound and runs in
   the server's thread pool; large batches can slow down API responses on the
   same instance. Large batches are bounded by `MAX_BATCH_SIZE`.
4. **No delivery guarantees.** Nothing guarantees a job will ever be processed
   after `202` is returned (the process could die immediately afterwards).

A production-hardening path would be a database-backed queue (e.g. a `jobs`
claim column polled by a separate worker process) or an external worker system
— intentionally out of scope here.

## Not included (per requirements)

Frontend, authentication, Redis/Celery, microservices, and deployment
configuration.
