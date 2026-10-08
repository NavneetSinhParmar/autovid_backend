> Render requirement update (2026-10-07): the user requested image/video rendering without duration or elapsed-time restrictions and without added logs. This overrides the older duration-limit tasks below. See [rendering instructions](../RENDERING.md).

# AutoVid Backend — Production Task List

## Final Target

Frontend integration review: see [FRONTEND_HANDOFF.md](FRONTEND_HANDOFF.md) for checked API paths, payload differences, UI changes, and backend dependencies. Existing checkmarks do not replace end-to-end production verification.

### Additional Integration Gaps (2026-09-28)

- [ ] Authorize private/combined download-counter mutations in public template routes.
- [ ] Replace legacy template download integration with render-job downloads.
- [ ] Verify authenticated media streaming, Range support, and public-template asset access.
- [ ] Expose upload constraints through a versioned API or shared deployment configuration.
- [ ] Define PATCH field-clearing semantics for nullable template media fields.
- [ ] Expose request-level idempotency for render and campaign submission.
- [ ] Add campaign validation preview with row-level errors before submission.
- [ ] Add independent customer/template/date filters to render history.
- [ ] Verify frontend adapters for list response keys and asynchronous TTS jobs.
- [ ] Verify tenant-specific cache clearing and public job capability handling in frontend.

Build the AutoVid backend as a production-ready multi-company SaaS platform capable of:

- 5,000+ application/API users
- 100–500 users submitting work around the same time
- Large bulk campaigns
- Hundreds/thousands of queued render jobs
- Fast image generation
- Asynchronous video generation
- Maximum generated video resolution: 720p
- Maximum template/source video duration: 5 minutes
- Maximum personalized generated video duration: 1 minute
- Horizontal worker scaling
- Strong company/data isolation

---

# P0 — Security

- [x] Remove committed secrets from repository.
- [ ] Rotate exposed MongoDB/JWT/API credentials.
- [x] Remove fixed/default superadmin credentials.
- [x] Add secure superadmin bootstrap process.
- [x] Prevent public registration from selecting privileged roles.
- [x] Protect media upload endpoints.
- [x] Protect render-job status endpoints.
- [x] Protect render download endpoints.
- [x] Protect private preview/render endpoints.
- [x] Add ownership validation to all private resources.
- [x] Ensure Company A cannot access Company B data.
- [x] Remove sensitive information from logs.
- [x] Move CORS configuration to environment settings.
- [x] Add rate limiting to authentication.
- [x] Add rate limiting to uploads.
- [x] Add rate limiting to rendering.
- [x] Add rate limiting to TTS/public expensive operations.
- [ ] Review JWT/token expiry and revocation strategy.

---

# P0 — Central Upload Validation

Create one reusable media-validation system.

## General

- [x] Validate extension.
- [x] Validate MIME type.
- [x] Validate actual media content where practical.
- [x] Validate file size.
- [x] Reject corrupt files.
- [x] Reject empty files.
- [x] Use configurable limits instead of route-level magic numbers.
- [ ] Avoid loading huge uploads completely into RAM.
- [x] Safely clean temporary upload files.
- [x] Return structured validation errors.

## Image

- [x] Support only approved formats.
- [x] Validate image dimensions.
- [x] Add configurable maximum image size.
- [x] Add configurable maximum image dimensions.
- [ ] Handle SVG only if it can be processed safely.

## Video

- [x] Validate using FFprobe.
- [x] Validate codec/container.
- [x] Validate resolution.
- [x] Validate duration.
- [x] Template/source video maximum duration = 5 minutes.
- [x] Reject invalid/corrupt videos.
- [x] Add configurable maximum upload MB.

## Audio

- [x] Validate audio format.
- [x] Validate duration.
- [x] Validate maximum file size.

Use structured errors such as:

`FILE_TOO_LARGE`

`INVALID_MEDIA_TYPE`

`INVALID_IMAGE`

`INVALID_VIDEO`

`VIDEO_DURATION_EXCEEDED`

`IMAGE_DIMENSIONS_EXCEEDED`

---

# P0 — Rendering Architecture

Production render flow:

User Request  
→ FastAPI  
→ Validate  
→ Create MongoDB Job  
→ Redis/Celery  
→ Return Job ID Immediately  
→ Worker  
→ FFmpeg  
→ Store Output  
→ Update Job  
→ Cleanup

- [x] Do not execute long FFmpeg operations inside HTTP requests.
- [x] Remove production dependency on the in-memory render queue.
- [x] Use Redis/Celery as the durable production queue.
- [ ] Preserve existing working rendering during migration.

---

# P0 — Separate Worker Queues

Create independent queues:

`render_image`

`render_video`

`tts`

- [x] Video jobs must not block image jobs.
- [x] TTS must not block rendering.
- [x] Route each Celery task to the correct queue.

---

# P0 — Render Job System

Every render job should contain:

- [x] job_id
- [x] company_id
- [x] customer_id
- [x] campaign_id
- [x] template_id
- [x] job_type
- [x] status
- [x] progress
- [ ] priority
- [x] retry_count
- [x] created_at
- [x] queued_at
- [x] started_at
- [x] completed_at
- [x] failed_at
- [x] render_duration
- [x] output_url
- [ ] error/error_code

Statuses:

`QUEUED`

`PROCESSING`

`COMPLETED`

`FAILED`

`CANCELLED`

---

# P0 — Render Isolation

Every render must use a unique job directory.

Example:

`jobs/{job_id}/input/`

`jobs/{job_id}/temp/`

`jobs/{job_id}/output/`

- [x] No shared temporary filenames.
- [x] No output collisions.
- [x] One failed job must not affect another job.
- [x] Cleanup must only remove files belonging to that job.

---

# P0 — Worker Reliability

- [x] Configurable retries.
- [ ] Retry only appropriate temporary failures.
- [x] Add render timeout.
- [x] Detect stuck PROCESSING jobs.
- [x] Handle worker crashes.
- [x] Make tasks idempotent where practical.
- [x] Prevent duplicate outputs during retries.
- [x] Record useful failure details.
- [x] Implement safe temporary-file cleanup.
- [x] Support graceful worker shutdown.

---

# P0 — Configurable Concurrency

Use environment configuration:

`VIDEO_WORKER_CONCURRENCY`

`IMAGE_WORKER_CONCURRENCY`

`TTS_WORKER_CONCURRENCY`

`FFMPEG_THREADS`

`MAX_RENDER_RETRIES`

`RENDER_TIMEOUT`

Do not hardcode worker concurrency.

Important:

500 concurrent submissions must NOT mean 500 simultaneous FFmpeg processes.

Extra jobs remain QUEUED until worker capacity becomes available.

---

# P1 — FFmpeg Optimization

Generated personalized videos:

- [x] Maximum output resolution = 720p.
- [x] Maximum generated duration = 1 minute.
- [x] H.264 video output.
- [x] AAC audio where applicable.
- [x] Add faststart for web/mobile playback.
- [x] Use sensible CRF/bitrate.
- [x] Use configurable FFmpeg preset.
- [x] Control FFmpeg threads.
- [x] Avoid unnecessary upscaling.
- [ ] Avoid unnecessary re-encoding where possible.
- [ ] Benchmark representative templates.
- [x] Track render duration.

---

# P1 — Campaign Architecture

Create proper campaign functionality.

Flow:

Company  
→ Campaign  
→ Template  
→ Customer/Bulk Data  
→ Validation  
→ Render Jobs  
→ Redis  
→ Workers  
→ Results

Campaign statuses:

`DRAFT`

`VALIDATING`

`QUEUED`

`PROCESSING`

`COMPLETED`

`PARTIALLY_COMPLETED`

`FAILED`

`CANCELLED`

Track:

- [x] total_jobs
- [x] queued_jobs
- [x] processing_jobs
- [x] completed_jobs
- [x] failed_jobs
- [ ] cancelled_jobs
- [x] progress_percentage

---

# P1 — Bulk Campaign Processing

- [x] CSV support.
- [x] XLSX support.
- [x] Validate required columns.
- [x] Validate customer data.
- [ ] Validate template placeholders.
- [ ] Return row-level errors.
- [x] Do not synchronously create/process thousands of expensive renders.
- [ ] Batch large job creation where appropriate.
- [ ] Allow retry of failed campaign jobs.
- [ ] Support campaign cancellation where practical.
- [ ] Prevent accidental duplicate campaign submission.

---

# P1 — MongoDB Optimization

Review collections:

- [x] users
- [x] companies
- [x] customers
- [ ] categories
- [x] templates
- [x] media
- [x] campaigns
- [x] render_jobs
- [ ] video_tasks

Review indexes for:

- [x] company_id
- [ ] customer_id
- [ ] template_id
- [x] campaign_id
- [x] job_id
- [x] status
- [x] created_at
- [x] email
- [x] username
- [x] distributed_id

Also:

- [x] Add appropriate unique indexes.
- [x] Add compound indexes according to actual queries.
- [ ] Standardize ObjectId/string handling.
- [ ] Remove unnecessary N+1 queries.
- [x] Use projections where useful.
- [x] Document index creation/migration strategy.

---

# P1 — Pagination & Filtering

Large listing APIs must support server-side:

- [x] pagination
- [ ] search
- [ ] filtering
- [ ] sorting
- [x] maximum page size

Apply to:

- [x] companies
- [x] customers
- [ ] categories
- [x] templates
- [x] media
- [x] campaigns
- [x] render jobs/history

Never return thousands of records by default.

---

# P1 — API Standardization

- [ ] Use Pydantic request schemas.
- [ ] Use typed response schemas.
- [ ] Reduce raw dictionary payloads.
- [ ] Centralize Mongo serialization.
- [ ] Centralize ObjectId handling.
- [x] Centralize errors.
- [ ] Standardize error codes.
- [x] Add request IDs.
- [ ] Add request timeouts where appropriate.
- [ ] Add structured production logging.
- [x] Remove debug print statements.

---

# P1 — Storage Architecture

Create:

`StorageService`

Implement:

`LocalStorageAdapter`

Prepare:

`S3CompatibleStorageAdapter`

- [x] Keep current local storage working initially.
- [ ] Make API and workers storage-independent.
- [x] Add safe private/public URL handling.
- [x] Add temporary-file cleanup.
- [ ] Add failed-render cleanup.
- [ ] Define media/output retention policy.
- [x] Track storage usage.
- [x] Prepare migration plan before moving existing media.

---

# P1 — Horizontal Scaling

Architecture must support:

Load Balancer  
→ Multiple FastAPI instances  
→ Redis  
→ MongoDB  
→ Multiple Celery Worker Servers  
→ Shared/Object Storage

Adding another render server should not require application redesign.

---

# P1 — Monitoring

Monitor:

- [ ] API response time
- [ ] API errors
- [x] Redis health
- [x] MongoDB health
- [x] Celery worker health
- [ ] FFmpeg availability
- [x] queue depth
- [x] queued jobs
- [x] processing jobs
- [x] completed jobs
- [x] failed jobs
- [x] average image render duration
- [x] average video render duration
- [ ] FFmpeg failures
- [x] storage usage

---

# P2 — Backend Cleanup

Only remove code after verifying it is unused.

Review:

- [ ] duplicate render implementations
- [ ] duplicate placeholder replacement
- [ ] duplicate serialization
- [ ] legacy rendering endpoints
- [ ] unused services
- [ ] old task models
- [ ] debug/reproduction scripts
- [ ] generated media committed to source
- [ ] unused imports
- [ ] unused dependencies
- [ ] commented/dead code
- [x] debug print statements

Do not blindly delete bulk-related code because bulk/campaign rendering is part of the future architecture.

---

# P1 — Automated Testing

Add tests for:

- [ ] authentication
- [ ] authorization
- [ ] company isolation
- [ ] uploads
- [ ] file-size restrictions
- [x] invalid MIME
- [ ] corrupt files
- [x] 5-minute source-video restriction
- [x] generated-video duration rules
- [ ] pagination
- [ ] campaign creation
- [ ] bulk validation
- [ ] queue submission
- [ ] render success
- [ ] render failure
- [ ] retry
- [ ] timeout
- [ ] cancellation
- [ ] idempotency
- [ ] duplicate submissions
- [ ] worker failure/recovery

---

# P1 — Load Testing

Test separately:

### API

- [ ] 10 concurrent users
- [ ] 50 concurrent users
- [ ] 100 concurrent users
- [ ] 250 concurrent users
- [ ] 500 concurrent users
- [ ] higher HTTP traffic testing toward 5K application traffic

### Rendering

Benchmark worker throughput separately.

Do NOT launch 500 FFmpeg processes on one server.

---

# Backend Final Acceptance

Backend is production-ready when:

- API remains responsive during rendering.
- 100–500 users can safely submit jobs.
- Excess jobs remain queued.
- Worker concurrency is controlled.
- Multiple worker machines can be added.
- Company data is isolated.
- Upload limits are enforced.
- Video rules are enforced.
- Campaigns can generate large batches safely.
- Failures do not affect unrelated jobs.
- Mongo queries remain efficient.
- Monitoring exposes queue/render problems.
- Automated tests pass.
- Production secrets are secure.

## Recommended Backend Order

1. Security
2. Upload validation
3. Mongo ID/index strategy
4. Pagination/API standardization
5. Queue unification
6. Separate image/video/TTS queues
7. Render-job reliability
8. FFmpeg optimization
9. Campaign/bulk system
10. Storage abstraction
11. Horizontal scaling
12. Monitoring
13. Tests/load tests
14. Legacy/unwanted-code cleanup
15. Production verification
