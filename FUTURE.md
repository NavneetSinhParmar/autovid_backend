# Future Work

> Initial audit roadmap. Several P0/P1 items are now implemented; the current `README.md` is the source of truth for shipped behavior.

Priorities: P0 = Critical, P1 = Important, P2 = Recommended, P3 = Optional.

## Current Missing Functionality

- P0: Replace startup-created fixed superadmin credentials with a secure bootstrap flow.
- P0: Remove committed real-looking credentials and rotate them if they were ever valid.
- P1: Finish or retire the admin role flow; `admin` routes exist but `admin` is not an allowed role.
- P1: Include or retire `app/routes/public_video.py` and its tokenized public video link flow.
- P1: Add persistent token revocation or short-lived access tokens plus refresh-token rotation.
- P2: Add email-based forgot-password/reset flow if users need self-service recovery.
- P2: Add object storage support if uploads/render outputs must survive deployments.

## Technical Improvements

- P0: Add request/response schemas for raw `data: dict` endpoints.
- P1: Standardize ObjectId/string storage for `company_id`, `customer_id`, `template_id`, and `user_id`.
- P1: Centralize Mongo serialization for ObjectIds and datetimes.
- P1: Remove duplicate route definitions such as `GET /templates/`.
- P2: Consolidate duplicated placeholder, company email hydration, media URL, and render helper logic.
- P2: Replace scattered `print()` debugging with structured logging.
- P2: Split large files such as `customer.py`, `template.py`, and `video_renderer.py`.

## Performance Improvements

- P0: Add rate limits/quotas for public preview, download, TTS, and render endpoints.
- P1: Add MongoDB indexes for auth, ownership, rendering, and public lookup fields.
- P1: Add pagination to company, customer, template, media, task, and public template lists.
- P1: Avoid N+1 user lookups in company listing.
- P1: Prefer Celery/Redis for production rendering rather than in-process API rendering.
- P2: Add cleanup/retention policies for render outputs, temp text files, font cache, and old media.

## Security Improvements

- P0: Rotate `.env.prod` credentials and remove the file from source control history if it was pushed.
- P0: Prevent public registration from choosing privileged roles.
- P0: Protect `/api/public/media/templates`, `/render-jobs/{job_id}`, and `/render-jobs/{job_id}/download`.
- P0: Enforce company ownership checks on template update/delete/preview/download and all customer update/delete paths.
- P1: Validate file content, size, MIME type, extension, and media duration for uploads.
- P1: Avoid logging full user/customer payloads and DB connection details.
- P1: Move CORS origins to environment configuration.
- P2: Add API abuse protection for CPU/GPU-heavy TTS and FFmpeg routes.

## UI/UX Improvements

No frontend source is present in this repository. Recommendations for the separate frontend:

- P1: Add loading/error/empty states for render jobs, customer import, TTS generation, and downloads.
- P1: Surface validation errors clearly for bulk upload row failures.
- P2: Add progress UI using `/tasks/{task_id}/status` and `/render-jobs/{job_id}`.
- P2: Add media cleanup/management views for companies.

## SEO Improvements

The backend has no SEO surface. Recommendations for the separate frontend:

- P2: Add page titles, descriptions, canonical URLs, and share metadata for public template pages.
- P3: Add structured data only if public template pages are intended to be indexed.

## Testing Improvements

- P0: Add auth/authorization tests for all roles.
- P1: Add CRUD tests for companies, customers, categories, templates, media.
- P1: Add render queue tests for success, failure, status, and download behavior.
- P1: Add public endpoint security tests.
- P1: Convert manual scripts into pytest tests or move them into a documented tools folder.
- P2: Add fixture-based Mongo test database setup.
- P2: Add static checks for formatting, imports, typing, and secrets.

## Monitoring / Logging Improvements

- P1: Add request IDs and structured JSON logs.
- P1: Capture render job errors without exposing sensitive tracebacks to users.
- P1: Add health checks for MongoDB, Redis, FFmpeg, and Celery worker availability.
- P2: Add metrics for queue depth, render duration, failures, TTS duration, storage growth, and public endpoint usage.

## Deployment Improvements

- P0: Ensure production never depends on committed `.env` files.
- P1: Add separate API and worker deployment docs.
- P1: Use persistent media storage or external object storage.
- P1: Remove unnecessary secret/context echoing from CI logs.
- P2: Add environment-specific CORS, BASE_URL, worker concurrency, and FFmpeg thread settings.
- P2: Add rollback and database backup guidance.

## Future Feature Ideas

- P2: Template versioning and rollback.
- P2: Render history with searchable status/error logs.
- P2: Bulk render jobs for customer cohorts.
- P2: Customer self-service public links with expiry and download limits.
- P3: Admin dashboard analytics for template usage and downloads.
- P3: Multi-language TTS voice grouping and preview samples.
