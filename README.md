# Bulk Certificate Generator API

A backend service built for the **AEREO SDE-Intern assignment**. Issuing
certificates one by one does not scale: each recipient needs an individually
addressed PDF, and a single bad record should not sink an entire batch. This
API accepts one request containing many recipients, validates the batch up
front, generates one PDF certificate per recipient as a **background job**,
and exposes **job tracking with live progress**, per-certificate metadata, and
PDF downloads.

- **Asynchronous bulk processing** — `202 Accepted` immediately, work continues
  in the background
- **Validation before anything is written** — an invalid batch leaves no
  partial rows
- **Failure isolation** — one recipient's generation failure never stops the
  rest of the batch
- **Job + certificate tracking** — statuses, counters, timestamps, and a
  `progress` fraction persisted in PostgreSQL

| | |
|---|---|
| **Live API** | <https://bulk-certificate-generator-vzzp.onrender.com> |
| **Swagger UI** | <https://bulk-certificate-generator-vzzp.onrender.com/docs> |
| **Health check** | <https://bulk-certificate-generator-vzzp.onrender.com/health> |
| **Source code** | <https://github.com/IrfanNaikwade28/BulkCertificateGenerator> |

## Table of contents

- [Live demo](#live-demo)
- [Features](#features)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [API reference](#api-reference)
- [Quick start — local development](#quick-start--local-development)
- [Example: create a bulk job](#example-create-a-bulk-job)
- [Database and configuration](#database-and-configuration)
- [Deployment guide](#deployment-guide)
- [Design decisions and trade-offs](#design-decisions-and-trade-offs)
- [Testing](#testing)
- [Future improvements](#future-improvements)

## Live demo

| Link | URL |
|---|---|
| Live API | <https://bulk-certificate-generator-vzzp.onrender.com> |
| Swagger UI | <https://bulk-certificate-generator-vzzp.onrender.com/docs> |
| Health check | <https://bulk-certificate-generator-vzzp.onrender.com/health> |
| Source code | <https://github.com/IrfanNaikwade28/BulkCertificateGenerator> |

The **`/health` endpoint checks database connectivity**: it runs `SELECT 1`
against PostgreSQL and returns `200 {"status":"ok"}` when the database is
reachable, or `503 {"detail":"Database unavailable"}` when it is not.

> The service is deployed on Render's free plan, which suspends instances
> after inactivity. The first request after idle may take roughly 30–60
> seconds while the instance wakes (it can briefly answer `503`). Subsequent
> requests respond normally.

## Features

- **Create bulk generation jobs** — `POST /api/v1/jobs` accepts a batch of
  recipients plus optional event details, returns `202` with a UUID job ID.
- **Validate event details and recipient data** — batch size limits, non-blank
  names, well-formed emails, duplicate-email rejection, and length limits on
  `certificate_title` / `event_name`. The whole batch is validated before any
  row is written.
- **Generate individual PDF certificates** — one predefined ReportLab
  template; the job's `certificate_title` and `event_name` are rendered into
  each certificate.
- **Track job status, progress, successes, and failures** — per-job counters
  (`processed`, `succeeded`, `failed`), a `progress` value from `0.0` to
  `1.0`, and `created_at` / `started_at` / `finished_at` timestamps.
- **Isolate failures per recipient** — a recipient whose PDF fails to render
  is recorded as `failed` with a sanitized `error_code`; the remaining
  recipients are still processed.
- **List certificates with pagination and status filtering** — `page`,
  `page_size` (max 200), and optional `status` query parameters.
- **Retrieve certificate metadata** — including a `download_url`; internal
  filesystem paths are never exposed.
- **Download individual PDF files** — served as `application/pdf` with a
  filename; `409` if the certificate is not ready yet.
- **Persist job and certificate metadata in PostgreSQL** — all state survives
  application restarts (local PostgreSQL in development, Neon in production).
- **Run database migrations with Alembic** — two versioned revisions build a
  schema from an empty database; no `create_all()` anywhere.
- **Health endpoint with a database connectivity check.**

Not included (and not claimed): Excel/CSV import, ZIP downloads, email
delivery, authentication, or a frontend.

## Architecture

### Request flow

```
Client
  → FastAPI routes (app/api/routes)          HTTP, status codes, response shaping
  → Pydantic schemas (app/schemas)           request validation, response models
  → SQLAlchemy models (app/models)           persistence in PostgreSQL
  → background processor (app/workers)       one fresh DB session per job,
  → ReportLab (app/services/pdf_service)     one short transaction per recipient,
  → file storage (STORAGE_DIR)               PDF written outside any transaction
Client ← certificate retrieval endpoints     status, list, metadata, download
```

`POST /api/v1/jobs` validates and persists the job plus one pending
certificate row per recipient in a single short insert-only transaction,
returns `202`, and only then schedules `process_job` through FastAPI
`BackgroundTasks`. The worker creates its **own** database session, marks the
job `processing`, and walks each certificate independently: mark
`processing` → commit → render the PDF → commit with `succeeded` (or roll
back and record `failed`). A transaction is never held open across PDF
rendering, and a certificate is only ever marked `succeeded` after its file
has been fully written (atomic temp-file + `os.replace`).

### Project structure

```
app/
├── main.py                   # app factory, routers, safe global error handler
├── config.py                 # pydantic-settings + DATABASE_URL normalization
├── db.py                     # engine, session factory, get_db dependency
├── models/                   # Job, Certificate + status enums (UUID PKs)
├── schemas/job.py            # Pydantic request/response models
├── services/
│   ├── job_service.py        # job creation, queries, progress/status logic
│   ├── pdf_service.py        # ReportLab rendering
│   └── storage.py            # internal file paths (never exposed)
├── workers/job_processor.py  # background loop with per-recipient isolation
└── api/routes/               # jobs.py, certificates.py, health.py
templates/certificate_layout.py   # the single predefined certificate template
alembic/                      # versioned migrations (2 revisions)
tests/                        # pytest suite (58 tests)
docker/                       # PostgreSQL init script (creates test database)
Dockerfile, docker-compose.yml, render.yaml
```

### Data model and job lifecycle

**`jobs`** — `id (UUID PK)`, `certificate_title`, `event_name`, `status`,
`total_count`, `processed_count`, `succeeded_count`, `failed_count`,
`created_at`, `started_at`, `finished_at`.

**`certificates`** — `id (UUID PK)`, `job_id (FK → jobs, CASCADE)`,
`recipient_name`, `email`, `status`, `error_code` (sanitized),
`file_size_bytes`, `created_at`, `generated_at`.

```
Job:       pending → processing → completed
                                      → completed_with_errors   (some failed)
                                      → failed                  (loop-level crash)
Certificate: pending → processing → succeeded | failed

progress = processed_count / total_count        (0.0 – 1.0)
```

Counters are incremented in the same transaction that persists each
certificate's terminal state, so reported progress always matches reality.

### Mermaid diagram

```mermaid
flowchart LR
    C[Client] -->|POST /api/v1/jobs| R[FastAPI routes]
    R --> V[Pydantic validation]
    V --> DB[(PostgreSQL)]
    R -->|BackgroundTasks| W[Job processor]
    W --> P[ReportLab PDF]
    P --> S[(STORAGE_DIR files)]
    W --> DB
    C -->|GET status / list / metadata / download| R
    H[Render health check] -->|GET /health| R
    R -->|SELECT 1| DB
```

## Technology stack

| Technology | Why it is used |
|---|---|
| **FastAPI** | Modern async-capable web framework; dependency injection for DB sessions, automatic OpenAPI/Swagger UI, and native Pydantic integration. |
| **Pydantic** (+ `pydantic-settings`) | Declarative request/response validation with precise `422` errors; environment-driven configuration in one place. |
| **SQLAlchemy 2.x** | Typed, declarative ORM (`Mapped` / `mapped_column`) with explicit session and transaction control — essential for the per-recipient commit strategy. |
| **PostgreSQL / Neon** | Relational guarantees (foreign keys, cascades, constraints) for job/certificate data. Local Dockerized PostgreSQL for development; **Neon** as the managed serverless database in production. |
| **Alembic** | Versioned, reviewable schema migrations that can build a database from empty — the only schema mechanism used (no `create_all()`). |
| **ReportLab** | Pure-Python PDF generation with precise layout control; no external binaries required in the container. |
| **pytest + HTTPX** | FastAPI's `TestClient` (built on HTTPX) exercises the real ASGI app end-to-end — routes, validation, background processing, and PDF downloads. |
| **Docker** | Reproducible image for local runs and for Render's Docker-based deploys; `docker-compose.yml` provides the local PostgreSQL. |
| **Render** | Deploys the GitHub repository with the included `render.yaml` Blueprint (free plan, Docker runtime, health-checked at `/health`). |

## API reference

Base URL (local): `http://localhost:8000` · Interactive docs: `/docs`

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| `GET` | `/health` | Liveness + database connectivity check | `200` | `503` |
| `POST` | `/api/v1/jobs` | Create a bulk generation job | `202` | `422` |
| `GET` | `/api/v1/jobs/{job_id}` | Job status, counters, progress, timestamps | `200` | `404`, `422` |
| `GET` | `/api/v1/jobs/{job_id}/certificates` | Paginated certificate results for a job | `200` | `404`, `422` |
| `GET` | `/api/v1/certificates/{certificate_id}` | Certificate metadata (no file paths) | `200` | `404`, `422` |
| `GET` | `/api/v1/certificates/{certificate_id}/download` | Download the generated PDF | `200` | `404`, `409`, `422` |

### `GET /health`

Checks database connectivity (`SELECT 1`).

```json
{"status": "ok"}
```

`503 {"detail": "Database unavailable"}` if the database cannot be reached.

### `POST /api/v1/jobs`

Request body:

| Field | Required | Rules |
|---|---|---|
| `recipients` | yes | 1–`MAX_BATCH_SIZE` (default 100) entries |
| `recipients[].name` | yes | non-blank after trimming, max 100 chars |
| `recipients[].email` | yes | valid email; duplicates within a batch rejected |
| `certificate_title` | no | 1–100 chars, default `CERTIFICATE OF ACHIEVEMENT` |
| `event_name` | no | 1–150 chars, default `the program` |

The **entire** request is validated before anything is written: a `422`
response means zero job and zero certificate rows were created.

`202 Accepted`:

```json
{
  "job_id": "2a558eff-252a-41d3-972b-d839bdb6431f",
  "status": "pending",
  "total_count": 2
}
```

### `GET /api/v1/jobs/{job_id}`

`200 OK` (values shown after processing finished):

```json
{
  "job_id": "2a558eff-252a-41d3-972b-d839bdb6431f",
  "status": "completed",
  "total_count": 2,
  "processed_count": 2,
  "succeeded_count": 2,
  "failed_count": 0,
  "progress": 1.0,
  "created_at": "2026-10-09T07:15:46.391610Z",
  "started_at": "2026-10-09T07:15:46.416809Z",
  "finished_at": "2026-10-09T07:15:46.459942Z"
}
```

`status` is one of `pending`, `processing`, `completed`,
`completed_with_errors`, `failed`. `progress` equals
`processed_count / total_count`. `started_at` / `finished_at` are `null`
until processing begins / ends. Unknown or malformed IDs → `404` /
`422`.

### `GET /api/v1/jobs/{job_id}/certificates`

Query parameters: `page` (≥ 1, default 1), `page_size` (1–200, default 50),
`status` (optional: `pending`, `processing`, `succeeded`, `failed`).

`200 OK`:

```json
{
  "job_id": "2a558eff-252a-41d3-972b-d839bdb6431f",
  "items": [
    {
      "certificate_id": "2d50cb5f-c4f7-4266-be89-04fcc05263ee",
      "recipient_name": "Aarav Mehta",
      "email": "aarav.mehta@example.com",
      "status": "succeeded",
      "error_code": null,
      "generated_at": "2026-10-09T07:15:46.440205Z"
    },
    {
      "certificate_id": "fc9abb43-073a-459b-918f-95cd9c9ba662",
      "recipient_name": "Diya Sharma",
      "email": "diya.sharma@example.com",
      "status": "succeeded",
      "error_code": null,
      "generated_at": "2026-10-09T07:15:46.454771Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 50
}
```

### `GET /api/v1/certificates/{certificate_id}`

`200 OK` — metadata only; filesystem paths are never included:

```json
{
  "certificate_id": "2d50cb5f-c4f7-4266-be89-04fcc05263ee",
  "recipient_name": "Aarav Mehta",
  "email": "aarav.mehta@example.com",
  "status": "succeeded",
  "error_code": null,
  "generated_at": "2026-10-09T07:15:46.440205Z",
  "job_id": "2a558eff-252a-41d3-972b-d839bdb6431f",
  "file_size_bytes": 2109,
  "created_at": "2026-10-09T07:15:46.398056Z",
  "download_url": "/api/v1/certificates/2d50cb5f-c4f7-4266-be89-04fcc05263ee/download"
}
```

A failed certificate reports `"status": "failed"` with the sanitized
`"error_code": "GENERATION_FAILED"` — internal exception details are logged
server-side only.

### `GET /api/v1/certificates/{certificate_id}/download`

`200 OK` with `Content-Type: application/pdf` and
`Content-Disposition: attachment; filename="certificate-<id>.pdf"`.

- Certificate not `succeeded` yet → `409 {"detail": "Certificate is not ready for download"}`
- Unknown ID → `404`; record exists but the file is gone (e.g. after a
  redeployment) → `404 {"detail": "Certificate file not available"}`

### Error format

All errors use FastAPI's standard shape: `{"detail": "..."}` with `422`
(validation), `404` (not found), `409` (conflict), `503` (database
unavailable). Internal paths, tracebacks, and raw exception messages are
never returned.

## Quick start — local development

Prerequisites: **Python 3.11+**, **Docker with Docker Compose**. Commands
below are for Linux (tested on Fedora); they are unchanged on macOS/WSL
except for your package manager.

```bash
# 1. Clone the repository
git clone https://github.com/IrfanNaikwade28/BulkCertificateGenerator.git
cd BulkCertificateGenerator

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure the environment (local development defaults)
cp .env.example .env

# 5. Start PostgreSQL — also creates the certgen_test database for the test suite
docker compose up -d db

# 6. Run Alembic migrations against the local database
alembic upgrade head

# 7. Start the API
uvicorn app.main:app --reload

# 8. Open Swagger UI
#    http://localhost:8000/docs

# 9. Run the test suite (the compose database must be running)
pytest
```

On Fedora, install the prerequisites first if needed:
`sudo dnf install python3 docker docker-compose` (or use Docker's official
install instructions), then add your user to the `docker` group.

Alternative — run the API and database fully in containers:

```bash
docker compose up --build    # API on http://localhost:8000, PostgreSQL on 5432
```

> `docker-compose.yml` is for **local development and tests only**. Production
> uses Neon PostgreSQL on Render — see the [deployment guide](#deployment-guide).

## Example: create a bulk job

The example below is copy-pasteable against the local server
(`http://localhost:8000`) — swap the base URL for
`https://bulk-certificate-generator-vzzp.onrender.com` to run it against the
deployed API. Replace every placeholder ID with the actual UUIDs returned by
your own requests.

```bash
BASE=http://localhost:8000

curl -X POST $BASE/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{
        "event_name": "Python Workshop 2026",
        "certificate_title": "Certificate of Participation",
        "recipients": [
          {"name": "Aarav Mehta", "email": "aarav.mehta@example.com"},
          {"name": "Diya Sharma", "email": "diya.sharma@example.com"}
        ]
      }'
```

`202 Accepted` (record the `job_id`):

```json
{
  "job_id": "2a558eff-252a-41d3-972b-d839bdb6431f",
  "status": "pending",
  "total_count": 2
}
```

Poll job status (substitute your `job_id`; processing takes well under a
second for small batches):

```bash
curl $BASE/api/v1/jobs/2a558eff-252a-41d3-972b-d839bdb6431f
```

```json
{
  "job_id": "2a558eff-252a-41d3-972b-d839bdb6431f",
  "status": "completed",
  "total_count": 2,
  "processed_count": 2,
  "succeeded_count": 2,
  "failed_count": 0,
  "progress": 1.0,
  "created_at": "2026-10-09T07:15:46.391610Z",
  "started_at": "2026-10-09T07:15:46.416809Z",
  "finished_at": "2026-10-09T07:15:46.459942Z"
}
```

List the certificates and pick an ID (substitute your `job_id`):

```bash
curl "$BASE/api/v1/jobs/2a558eff-252a-41d3-972b-d839bdb6431f/certificates?page=1&page_size=50"
```

```json
{
  "job_id": "2a558eff-252a-41d3-972b-d839bdb6431f",
  "items": [
    {
      "certificate_id": "2d50cb5f-c4f7-4266-be89-04fcc05263ee",
      "recipient_name": "Aarav Mehta",
      "email": "aarav.mehta@example.com",
      "status": "succeeded",
      "error_code": null,
      "generated_at": "2026-10-09T07:15:46.440205Z"
    },
    {
      "certificate_id": "fc9abb43-073a-459b-918f-95cd9c9ba662",
      "recipient_name": "Diya Sharma",
      "email": "diya.sharma@example.com",
      "status": "succeeded",
      "error_code": null,
      "generated_at": "2026-10-09T07:15:46.454771Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 50
}
```

Retrieve one certificate's metadata (substitute your `certificate_id`):

```bash
curl $BASE/api/v1/certificates/2d50cb5f-c4f7-4266-be89-04fcc05263ee
```

```json
{
  "certificate_id": "2d50cb5f-c4f7-4266-be89-04fcc05263ee",
  "recipient_name": "Aarav Mehta",
  "email": "aarav.mehta@example.com",
  "status": "succeeded",
  "error_code": null,
  "generated_at": "2026-10-09T07:15:46.440205Z",
  "job_id": "2a558eff-252a-41d3-972b-d839bdb6431f",
  "file_size_bytes": 2109,
  "created_at": "2026-10-09T07:15:46.398056Z",
  "download_url": "/api/v1/certificates/2d50cb5f-c4f7-4266-be89-04fcc05263ee/download"
}
```

Download the PDF (writes `certificate-<id>.pdf` to the current directory):

```bash
curl -OJ $BASE/api/v1/certificates/2d50cb5f-c4f7-4266-be89-04fcc05263ee/download
# HTTP 200 · Content-Type: application/pdf ·
# Content-Disposition: attachment; filename="certificate-2d50cb5f-....pdf"
```

## Database and configuration

Configuration is loaded by `pydantic-settings` from environment variables
(overriding an optional local `.env`). See [`.env.example`](.env.example) —
it contains **only local development placeholders, never real credentials**,
and `.env` is git-ignored.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | yes (production) | `postgresql+psycopg://certgen:certgen@localhost:5432/certgen` | PostgreSQL connection string. `postgres://` and `postgresql://` schemes are automatically normalized to SQLAlchemy's `postgresql+psycopg://`; query parameters such as `sslmode=require` are preserved. |
| `MAX_BATCH_SIZE` | no | `100` | Maximum recipients accepted in one job. |
| `STORAGE_DIR` | no | `storage/certificates` | Internal directory for generated PDFs. Never exposed through the API. |
| `LOG_LEVEL` | no | `INFO` | Python logging level. |
| `PORT` | set by Render | `8000` | The container binds `0.0.0.0:$PORT`; Render injects its own value (default `10000`). Not read by the app itself. |

**Neon on Render, without exposing credentials:** the Neon connection string is
stored **only** as the `DATABASE_URL` environment variable in the Render
dashboard. In `render.yaml` it is declared with `sync: false`, so Render prompts
for the value and never writes it into the repository. The application and
Alembic both read the same setting (`get_settings().database_url`), so
migrations and the running API always target the same database. Never commit a
real connection string, and never paste one into an issue or the README.

## Deployment guide

Production topology: **Render Web Service (Docker) + Neon PostgreSQL**. There
is no local PostgreSQL container in production.

### 1. Connect the repository

Render Dashboard → **New → Blueprint** → connect
<https://github.com/IrfanNaikwade28/BulkCertificateGenerator>. Render detects
the included [`render.yaml`](render.yaml):

- `runtime: docker`, `dockerfilePath: ./Dockerfile`, `plan: free`
- `healthCheckPath: /health`
- `DATABASE_URL` with `sync: false` (secret, entered in the dashboard)
- non-secret defaults: `LOG_LEVEL=INFO`, `MAX_BATCH_SIZE=100`,
  `STORAGE_DIR=/app/storage/certificates`

### 2. Configure `DATABASE_URL` as a secret

When prompted (or under the service's **Environment** tab), paste your Neon
connection string (`postgres://…?sslmode=require`) as the value of
`DATABASE_URL`. It lives only in Render — the Dockerfile defines no build
`ARG` and `.dockerignore` excludes `.env`, so the secret never enters the
image or Git.

### 3. Alembic migration workflow

The container start command in the `Dockerfile` is:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

So on every deploy (with the single free-plan instance) migrations run
**exactly once, before uvicorn starts serving traffic**. Alembic reads the
same `DATABASE_URL` as the app. To migrate explicitly instead — recommended
once before your first deploy — run from your machine:

```bash
DATABASE_URL='postgres://USER:PASSWORD@HOST/DATABASE?sslmode=require' \
  alembic upgrade head
```

or use Render Dashboard → **Shell** → `alembic upgrade head`. Never use
`Base.metadata.create_all()`; if you scale beyond one instance, remove the
migration from the start command so multiple workers never run DDL
concurrently (e.g. use Render's Pre Deploy Command).

### 4. Verify the deployed API

```bash
curl https://bulk-certificate-generator-vzzp.onrender.com/health
# → 200 {"status":"ok"}   (503 {"detail":"Database unavailable"} if Neon is down)

# Interactive docs
# https://bulk-certificate-generator-vzzp.onrender.com/docs

# Smoke test
curl -X POST https://bulk-certificate-generator-vzzp.onrender.com/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"event_name":"Python Workshop 2026",
       "certificate_title":"Certificate of Participation",
       "recipients":[{"name":"Test User","email":"test@example.com"}]}'
# → 202 {"job_id":"...","status":"pending","total_count":1}
```

Render uses `/health` as the service health check for the blueprint; a `503`
there marks the instance unhealthy.

## Design decisions and trade-offs

**Why a relational database.** Jobs and certificates have a strict one-to-many
relationship with referential integrity, cascading deletes, and
per-recipient counters that must stay consistent with row states. PostgreSQL
gives exactly that (UUID keys, foreign keys, transactional counter updates),
and Alembic makes the schema reproducible from empty.

**Why background processing.** Generating N PDFs synchronously inside the
request would block clients for the whole batch. `BackgroundTasks` lets the
API validate, persist, and return `202` in milliseconds while rendering
continues behind it — with no additional infrastructure.

**Why each recipient is handled independently.** Every certificate is wrapped
in its own `try/except` and its own short transaction. A render error marks
that one certificate `failed` (sanitized `error_code`) and the loop moves on;
failures are counted so the job finishes as `completed_with_errors` rather
than aborting.

**Why rendering and transactions are separated.** Holding a database
transaction open across CPU-bound PDF rendering would pin connections and
risk long lock times. The worker commits the `processing` state first,
renders with no open transaction, then commits the final state. File writes
are atomic (temp file + `os.replace`), and `succeeded` is only persisted
after the file fully exists — so a certificate is never marked successful
without its PDF.

**Why Alembic.** Schema changes must be explicit, versioned, and replayable
against a fresh database. Two migrations take an empty Neon database to
`head` deterministically, and the test suite runs the same migrations on
every test session.

### Current limitations

- **`BackgroundTasks` is in-process, not a durable queue.** Jobs are held in
  application memory. There is no retry, no resume, and no cross-instance
  visibility.
- **A restart can strand jobs.** If the process restarts mid-job, remaining
  certificates stay `pending` and nothing automatically picks them up (a
  crash of the loop marks the job `failed`). Database metadata itself is
  unaffected.
- **Render's local filesystem is ephemeral.** PDFs live under `STORAGE_DIR`
  inside the container, so a redeploy or restart can delete previously
  generated files while their metadata remains in Neon. Downloads then
  return a graceful `404 "Certificate file not available"` — never a path
  leak or a 500.
- **Not production-grade durability.** Persistent object storage (or a
  persistent disk) plus a durable task queue are the correct long-term
  answers; **neither is implemented today**.

## Testing

```bash
docker compose up -d db   # the suite needs the local PostgreSQL
pytest
```

**Result: `58 passed`** (verified by running the full suite; takes ~3 seconds
once the database is up). The suite uses the dedicated `certgen_test` database
created by `docker/initdb` and a temporary storage directory — your local data
is untouched, and migrations are applied by the test session fixture.

| Area | File |
|---|---|
| Health endpoint | `tests/test_health.py` |
| Job creation — 202, UUIDs, persisted rows, background completion | `tests/test_job_creation.py` |
| Request validation — batch limits, emails, duplicates, blanks, types, title/event rules | `tests/test_validation.py` |
| Status, counters, progress fraction, timestamps | `tests/test_progress_and_status.py` |
| Per-recipient failure isolation + sanitized errors | `tests/test_failure_isolation.py` |
| Certificate listing, pagination, status filter | `tests/test_certificate_listing.py` |
| Metadata shape, PDF downloads, path/traceback leakage checks | `tests/test_certificate_metadata_and_download.py` |
| PDF content — submitted title/event rendered, defaults kept | `tests/test_pdf_content.py` |
| `DATABASE_URL` normalization and settings behaviour | `tests/test_config.py` |

## Future improvements

The following are **future work, not current features**:

- Durable background workers (database-backed queue or external task system)
- Persistent object storage for generated PDFs (or a Render persistent disk)
- Bulk ZIP download of a job's certificates
- CSV/XLSX recipient import
- Authentication and rate limiting
