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

> `docker-compose.yml` is for **local development and tests only**. Production
> does not use it or any local PostgreSQL container — see
> [Deployment (Neon + Render)](#deployment-neon--render).

## Deployment (Neon + Render)

Production topology: **Render Web Service (Docker) + Neon PostgreSQL**.
No local database, Redis, or Celery involved.

### Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | **Yes (production)** | local dev URL | Neon connection string. `postgres://` and `postgresql://` schemes are automatically normalized to SQLAlchemy's `postgresql+psycopg://`; query parameters such as `sslmode=require` are preserved. Set only in the Render dashboard — never committed. |
| `PORT` | Set by Render | `8000` | Render injects its own port (default `10000`); the container binds `0.0.0.0:$PORT`. Locally defaults to 8000. |
| `MAX_BATCH_SIZE` | No | `100` | Maximum recipients per job. |
| `STORAGE_DIR` | No | `storage/certificates` | Internal PDF directory (set to `/app/storage/certificates` in `render.yaml`). Never exposed via the API. |
| `LOG_LEVEL` | No | `INFO` | Python logging level. |

`.env.example` contains only local development placeholders — no real
credentials. Render environment variables are translated to Docker build args
during image build; this Dockerfile defines no `ARG`, and `.dockerignore`
excludes `.env`, so secrets never enter the image.

### 1. Create the Neon database

1. Create a project at neon.tech and a database (e.g. `certgen`).
2. Copy the connection string from the dashboard. It looks like
   `postgres://USER:PASSWORD@HOST/DATABASE?sslmode=require` — treat it as a
   secret. The app accepts it as-is (normalization happens in code).
3. Neon endpoints allow all IP addresses by default, so no IP allowlist entry
   is needed for Render.

### 2. Configure Render

Two equivalent options:

**Option A — Render Blueprint (recommended):**

1. Render Dashboard → **New → Blueprint** → connect this GitHub repository.
2. Render detects `render.yaml` (free plan, Docker, health check `/health`).
3. When prompted, paste your Neon connection string for `DATABASE_URL`
   (`sync: false` — the value is stored only in Render, never in Git).
4. Click **Apply**.

**Option B — Web Service (manual):**

1. Render Dashboard → **New → Web Service** → connect the repository.
2. Settings: **Runtime: Docker**, **Dockerfile Path: `./Dockerfile`**,
   **Instance Type: Free**, **Health Check Path: `/health`**.
3. Add environment variables (see the table above), at minimum `DATABASE_URL`.
4. Deploy.

### 3. Run migrations against Neon

Alembic reads the exact same `get_settings().database_url` as the application,
so migrations always target the configured Neon database. Never use
`Base.metadata.create_all()` — Alembic is the only schema mechanism.

The container start command runs migrations **before** uvicorn serves traffic:

```dockerfile
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

With Render's single instance (free plan) this executes exactly **once per
deploy, before any request is served** — never concurrently from multiple
workers.

You can also run migrations explicitly (recommended before your first deploy,
or any time you need a one-off run):

```bash
# From your machine, against Neon (run from the project root):
DATABASE_URL='postgres://USER:PASSWORD@HOST/DATABASE?sslmode=require' \
  alembic upgrade head

# Or inside the deployed container via Render Dashboard → Shell:
alembic upgrade head
```

> **If you ever scale beyond one instance:** remove `alembic upgrade head`
> from the Dockerfile `CMD` and run migrations as a single separate step
> (Render **Pre Deploy Command**: `alembic upgrade head`, or a one-off shell
> run) so multiple workers never run DDL concurrently.

**Safe order for a fresh production setup:**

1. Create the Neon database and copy its connection string.
2. Run `alembic upgrade head` against Neon once (command above) → schema is
   at head (`525c1946cc95` → `5d32a190fea2` on a fresh database).
3. Create the Render service/Blueprint with `DATABASE_URL` set.
4. Deploy; the container re-runs `alembic upgrade head` (a no-op) then starts
   uvicorn.
5. Verify `/health`, `/docs`, and a sample job.

### 4. Verify the deployment

```bash
# Health (checks database connectivity; 503 if Neon is unreachable)
curl https://YOUR-SERVICE.onrender.com/health
# → {"status":"ok"}

# Interactive API docs
open https://YOUR-SERVICE.onrender.com/docs

# Sample job
curl -X POST https://YOUR-SERVICE.onrender.com/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"certificate_title":"CERTIFICATE OF ACHIEVEMENT",
       "event_name":"the program",
       "recipients":[{"name":"Test User","email":"test@example.com"}]}'
# → 202 {"job_id":"...","status":"pending","total_count":1}
```

### 5. Storage and background-task limitations (read before shipping)

- **PDF storage is local and ephemeral on Render's free plan.**
  Certificates are written under `STORAGE_DIR` inside the container. Any
  redeploy, restart, or crash replaces that filesystem, so previously
  generated PDFs disappear while their metadata remains in Neon. The download
  endpoint then returns a graceful `404 Certificate file not available`
  (never a path leak or 500). Job/certificate history, statuses, and counts
  are unaffected because they live in Neon.
  - Optional: attach a paid **persistent disk** mounted at `STORAGE_DIR` to
    survive redeploys. Not configured in `render.yaml` to avoid paid
    resources; add it only if you need durable PDFs.
- **`BackgroundTasks` are in-process and not durable.** Jobs are queued in
  memory: a restart or deploy mid-job leaves remaining certificates `pending`
  forever (no retry/resume), and jobs are only processed by the instance that
  accepted them. This is a documented design trade-off for the assignment —
  it is **not** production-grade durability. A durable queue (DB-backed
  worker or external job system) would be the upgrade path.

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
