# AutoVid Backend

FastAPI backend for multi-company customer/template management and asynchronous personalized image, video, and TTS generation. MongoDB stores application and job state, Redis/Celery handles bounded background work, FFmpeg renders media, and Kokoro provides speech synthesis.

## Architecture

All expensive operations follow the same production path:

```text
HTTP request -> validation/ownership check -> MongoDB job -> Redis queue
             -> immediate 202 + job_id -> bounded worker -> secured result
```

Queues are isolated so slow videos do not block images or speech:

- `render_video`: H.264/AAC video jobs
- `render_image`: image jobs
- `tts`: direct TTS and dynamic voice preparation
- `campaigns`: bulk campaign expansion
- `maintenance`: stuck-job recovery

Every render uses `media/render_jobs/{job_id}/temp` and `media/render_jobs/{job_id}/output`. Static `/media` access explicitly blocks `render_jobs`; results are downloaded through the owner-checked render-job endpoint.

## Security Model

- Public registration can only create `customer` users.
- Company accounts and superadmins are created only through privileged flows.
- The optional initial superadmin comes from `BOOTSTRAP_SUPERADMIN_*` environment variables; no fixed password exists in source.
- Company-owned customers, templates, media, campaigns, tasks, jobs, and outputs are tenant-filtered.
- Public template renders receive a high-entropy job capability token. Job status/download requires that token or authenticated ownership.
- CORS origins come from `CORS_ORIGINS`.
- Redis-backed rate limits protect authentication, upload, render, TTS, and campaign submission. A process-local fallback preserves limits during Redis failure.
- `.env` is ignored. `.env.prod` contains placeholders only. Previously exposed credentials must still be revoked at their providers and removed from Git history.

## Media Validation

`app/services/media_validator.py` is the shared validation boundary.

- Images: JPG/JPEG, PNG, WebP decoded with Pillow; self-contained SVG is converted to PNG with CairoSVG and native Cairo. External SVG resources are rejected.
- Video: MP4, MOV, WebM; FFprobe verifies stream, codec, resolution, corruption, and media duration.
- Audio: MP3, WAV, M4A, AAC, OGG; FFprobe verifies stream and duration.
- Stable errors include `VIDEO_TOO_LONG`, `FILE_TOO_LARGE`, `INVALID_MEDIA_TYPE`, `INVALID_VIDEO`, `UNSUPPORTED_FORMAT`, and `IMAGE_DIMENSIONS_EXCEEDED`.
- Generated video is checked after rendering: at most 1280x720, H.264 video, AAC audio when present. FFmpeg uses controlled threads, max 30 FPS, CRF/preset controls, and `+faststart` without upscaling.

## Render Jobs

Statuses are `QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`, and `CANCELLED`. Documents include ownership IDs, type, progress, retry count, timestamps, render duration, output URL, and structured error data.

Useful endpoints:

- `POST /tasks/generate`: queue a company/customer video.
- `POST /templates/{id}/preview`: queue a template preview.
- `POST /templates/{id}/preview/{customer_id}`: queue a personalized preview.
- `POST /public/templates/{id}/preview`: queue a public render and return a capability token.
- `POST /kokoro/tts`: queue speech generation.
- `GET /render-jobs`: paginated company job history.
- `GET /render-jobs/{job_id}`: owner/capability status.
- `GET /render-jobs/{job_id}/download`: owner/capability download.
- `POST /render-jobs/{job_id}/cancel`: cancel a queued owned job.

Workers atomically claim only queued jobs. Late acknowledgement and worker-loss rejection recover crashes; bounded exponential retries handle transient failures; Celery beat requeues stale processing jobs. Idempotency keys prevent duplicate task/campaign job creation.

## Campaigns

Campaigns connect a company, template, and up to 5,000 customer records. `POST /campaigns` accepts customer IDs, while `POST /campaigns/upload` accepts CSV/XLSX data with `customer_id`, `distributed_id`, or `email`. The API persists one campaign and queues expansion; a campaign worker creates individual jobs outside the HTTP request.

Campaign state tracks total, queued, processing, completed, failed, and progress percentage. Campaign and render-job list APIs are paginated.

## Storage

`StorageService` defines the storage boundary. `LocalStorageService` is the current adapter; generated paths are traversal-safe and filenames are randomized. An S3-compatible adapter can replace it without changing upload routes.

Local storage is suitable for one shared-volume deployment. Horizontally scaled workers require shared object storage or a shared filesystem.

## MongoDB

Startup creates unique/compound indexes for users, companies, customers, templates, media, render jobs, and campaigns. Legacy customer `linked_company_id` ObjectIds are normalized to canonical strings before index creation; read paths remain mixed-type compatible during rollout.

Unique index creation can fail if existing production data contains duplicates. Audit and repair duplicate usernames, emails, and customer distributed IDs before first deployment.

## Configuration

Local development loads `.env.local` from the project root automatically, including
Uvicorn reload subprocesses and Celery workers. Precedence is process environment,
then `.env.local`, then `.env` as a compatibility fallback. Files are resolved
relative to the project, not the current working directory. `.env.local` is ignored
by Git. Set `MONGO_URL`, `DATABASE_NAME`, and a unique `SECRET_KEY` there; restart
Uvicorn after changing environment files. `.env.prod` is not automatically loaded.

Copy `.env.example` into your local environment and provide real values through a secret manager in production. Required values are `MONGO_URL`, `DATABASE_NAME`, and `SECRET_KEY`.

Important capacity settings:

```text
CELERY_RENDER_CONCURRENCY=2
MAX_CONCURRENT_VIDEO_RENDERS=2
IMAGE_WORKER_CONCURRENCY=4
TTS_WORKER_CONCURRENCY=2
FFMPEG_THREADS=1
FFMPEG_FILTER_THREADS=1
CELERY_WORKER_PREFETCH_MULTIPLIER=1
FFMPEG_PRESET=veryfast
FFMPEG_CRF=22
MAX_RENDER_RETRIES=2
```

Upload, duration, image dimension, CORS, rate limit, stale-job, Redis, and FFmpeg settings are documented in `.env.example`.

Video rendering decodes still overlays once and composites at output resolution.
See [VIDEO_PERFORMANCE.md](../VIDEO_PERFORMANCE.md) for measured timing, quality
comparisons, concurrent benchmarks and the full-resolution composition opt-out.

## Running

For single-process local development, set `APP_ENV=development` and
`RENDER_QUEUE_BACKEND=memory`. Render jobs run in separate bounded background pools with
MongoDB status and secured downloads, without Redis/Celery workers. Production
uses `RENDER_QUEUE_BACKEND=celery` and the workers below. Configurable source/output
duration ceilings and FFmpeg elapsed timeouts now apply. Older rendering and
concurrency documents may describe the previous unlimited contract; the current
[deployment and scaling guide](deploy/README.md) takes precedence.

For an existing local database containing duplicate user email/username records,
`APP_ENV=development` and `ALLOW_LOCAL_LEGACY_USER_INDEXES=true` allow startup
with warnings while those two unique indexes await cleanup. This exception only
accepts a loopback MongoDB host; it does not delete records or suppress other
index failures. Ambiguous logins return `409 AMBIGUOUS_ACCOUNT`. Uniqueness is
not guaranteed for concurrent account creation until the duplicates are repaired.
Do not use this compatibility mode for production. Run
`python -m app.db.audit_duplicates` to review affected records.

Install FFmpeg/FFprobe, MongoDB, and Redis, then install Python dependencies:

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run workers as separate processes so each queue has independent capacity:

```bash
python scripts/run_worker.py render_video
python scripts/run_worker.py render_image
python scripts/run_worker.py tts
python scripts/run_worker.py campaigns,maintenance
python scripts/run_worker.py beat
```

Equivalent process definitions are in `Procfile`.

The existing `app.worker.video_worker.celery_app` entry point and `render_video`
queue are preserved. Workers share a host-wide FFmpeg budget with image and TTS
encoding; extra jobs wait and low-memory admission retries without claiming a job.
The supported deployment is one Linux host with one shared lock directory, not
independent hosts. Ten is a configurable benchmark target, not a safe default.
See [audit](CONCURRENCY_AUDIT.md), [exact Linux deployment/restart commands and
load testing](deploy/README.md), and [validation results](VALIDATION_RESULTS.md).

## Monitoring

`GET /health` checks MongoDB. Superadmin-only `GET /monitoring/metrics` reports job counts, queue depths, average render durations by type, Mongo/Redis health, and local storage usage. HTTP responses include `X-Request-ID` and `X-Response-Time-Ms`.

## Tests

Run the real HTTP company/auth integration suite with local MongoDB:

```bash
python test_company_api.py
```

It starts an isolated API process and temporary database, tests CRUD/passwords/
permissions/logos and company resource listings, then cleans up its own fixtures.
See [API_TESTING.md](API_TESTING.md) for prerequisites and exact coverage.

Run the standard-library suite and existing FIFO regression test:

```bash
python -m unittest discover -s tests -v
python test_render_queue_fifo.py
```

The k6 scenario in `load_tests/render_submit.js` stages 100, 250, and 500 concurrent submitters. Supply `BASE_URL`, `ACCESS_TOKEN`, `TEMPLATE_ID`, and `CUSTOMER_ID`. This benchmarks API acceptance/queueing separately from FFmpeg throughput.

For a single 100-request mixed image/video burst plus optional concurrent uploads,
use `load_tests/media_100.js`. See [CONCURRENCY.md](../CONCURRENCY.md) for worker
settings, bounded uploads, media caching, repeated-file reuse and benchmark limits.

## Deployment Gate

Before production rollout:

1. Revoke previously committed database/JWT credentials and purge them from repository history.
2. Configure MongoDB, Redis, secret manager values, CORS, storage, and all worker processes.
3. Resolve pre-existing duplicate data before index creation.
4. Run integration tests against real MongoDB/Redis/FFmpeg/Kokoro services.
5. Run staged submission load tests and a separate media throughput benchmark on production-sized workers.
