# Project Audit

> Historical pre-hardening snapshot. The current `README.md` supersedes resolved security and queue findings below.

## Current Architecture Summary

This repository is a FastAPI backend for AutoVid video/image generation. It uses MongoDB for application data, local filesystem storage for uploaded/generated media, FFmpeg for rendering, Kokoro/Torch for TTS, an in-memory FIFO queue for synchronous preview/download renders, and Celery/Redis for queued task renders. The checkout does not include frontend source.

Entry point: `app/main.py`

Included routers: auth, company, customer, admin, media, template, video_task, task, category, public, public_templates, voise_over, render_jobs.

Existing but not included: `app/routes/public_video.py`.

## Current Feature Inventory

| Feature | Purpose | Main files | DB collections | Status |
| --- | --- | --- | --- | --- |
| App startup/static media | FastAPI setup, CORS, `/media`, seed superadmin, start render worker | `app/main.py` | `users` | Partial; seeds fixed credentials |
| Authentication | Register/login/logout/profile/password reset | `app/routes/auth.py`, `app/utils/auth.py`, `app/models/user_model.py` | `users`, `companies`, `customers` | Partial; public role registration, in-memory logout |
| Company management | Superadmin creates/lists/updates/deletes companies | `app/routes/company.py`, `app/models/company_model.py`, `app/services/storage.py` | `users`, `companies`, `customers`, `templates`, `media`, `video_tasks` | Partial; detail endpoint unauthenticated |
| Customer management | Create/import/list/get/update/delete customers | `app/routes/customer.py`, `app/models/customer_model.py` | `users`, `customers`, `companies` | Partial; bulk upload exists, auth/ownership gaps remain |
| Admin management | List/get/update admin users | `app/routes/admin.py` | `users` | Incomplete/legacy; no allowed `admin` role |
| Category management | Company-scoped categories | `app/routes/category.py`, `app/models/category.py` | `categories`, `companies` | Working |
| Media upload | Store files under local media root | `app/routes/media.py`, `app/services/storage.py` | `media` | Working with limited validation |
| Template management | CRUD templates and render previews/downloads | `app/routes/template.py`, `app/models/template_model.py`, `app/services/video_renderer.py` | `templates`, `media`, `companies`, `customers`, `video_tasks` | Partial; duplicate route, ownership gaps |
| Public template APIs | Public browse/preview/download/counters | `app/routes/public.py`, `app/routes/public_templates.py` | `templates`, `companies`, `media` | Partial; public upload/render risk |
| Legacy video task APIs | Private/public video task helpers | `app/routes/video_task.py` | `video_tasks`, `templates`, `customers`, `companies` | Partial/legacy; overlaps `/tasks` |
| Celery render tasks | Queue generation and status | `app/routes/task.py`, `app/services/render_queue.py`, `app/services/celery_app.py`, `app/worker/video_worker.py` | `video_tasks`, `render_jobs` | Working if Redis/worker configured |
| Render job APIs | Status/download render outputs | `app/routes/render_jobs.py` | `render_jobs` | Partial; public access |
| TTS | Voices, health, synthesize audio media | `app/routes/voise_over.py`, `app/services/kokoro_tts.py` | `media`, `companies` | Working; resource-heavy |
| Placeholder replacement | Fill customer/company fields in templates | `app/utils/placeholders.py`, duplicated route helpers | n/a | Working but duplicated |
| Deployment | Docker image and GitHub Actions | `Dockerfile`, `Procfile`, `.github/workflows/azure-webapps-python.yml` | n/a | Partial |

## API Findings

FastAPI registered 61 routes including OpenAPI/docs during inspection.

| Method | Endpoint | Purpose | Auth | Role/Permission | Handler | Frontend Usage | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| POST | `/auth/register` | Register user | No | Caller-selected role | `register_user` | Likely external frontend | Risky |
| POST | `/auth/login` | Login | No | Public | `common_login` | Likely | Working |
| POST | `/auth/logout` | Logout | Yes | Any | `logout_user` | Likely | Partial |
| GET | `/auth/profile` | Profile | Yes | Any | `get_profile` | Likely | Possibly broken for company without logo |
| PATCH | `/auth/forgot-password` | Superadmin password reset | Yes | superadmin | `change_user_password` | Admin UI likely | Misnamed |
| PATCH | `/auth/reset-password` | Password reset/change | Yes | any/superadmin | `reset_password` | Likely | Working |
| CRUD | `/company/*` | Companies | Mixed | mostly superadmin | `company.py` | Likely | Partial |
| CRUD | `/customer/*` | Customers/import | Yes | superadmin/company | `customer.py` | Likely | Partial |
| CRUD | `/category/*` | Categories | Yes | superadmin/company | `category.py` | Likely | Working |
| POST | `/media-api/upload` | Upload media | Yes | superadmin/company | `upload_media` | Likely | Working |
| CRUD/render | `/templates/*` | Templates | Mixed | company/public depending route | `template.py` | Likely | Partial |
| GET/POST | `/api/public/*` | Public templates/upload | No | Public | `public.py` | Likely public | Upload risky |
| POST/PATCH | `/public/templates/*` | Public preview/download/counts | No | Public | `public_templates.py` | Likely | Partial |
| GET/POST | `/video-task/*` | Legacy video task flow | Mixed | company/public | `video_task.py` | Unknown | Partial/legacy |
| POST/GET | `/tasks/*` | Celery render flow | Yes | company | `task.py` | Likely | Needs worker |
| GET | `/render-jobs/{job_id}` | Job status | No | Public | `render_job_status` | Likely | Auth gap |
| GET | `/render-jobs/{job_id}/download` | Job output | No | Public | `render_job_download` | Likely | Auth gap |
| GET/POST | `/kokoro/*` | TTS | Mixed | voices/health public, tts protected | `voise_over.py` | Likely | Working |

APIs with no obvious frontend evidence should be verified externally because no frontend source is present.

## Frontend Findings

- No frontend source, components, pages, forms, layouts, SEO, or state-management code exists in this repository.
- CORS allows localhost, localhost:3000, a Netlify URL, and an API domain.
- Frontend-to-backend contracts are inferred only from route names and responses.

## Database Findings

Important relationships:

- `users._id` -> `companies.user_id`, often stored as string.
- `users._id` -> `customers.user_id`, stored as ObjectId in customer creation.
- `companies._id` -> `customers.linked_company_id`, sometimes ObjectId and sometimes compared as string.
- `companies._id` -> `templates.company_id`, stored as string.
- `templates._id` and `customers._id` -> `video_tasks.template_id/customer_id`, mixed ObjectId/string across old/new routes.
- `render_jobs.job_id` -> `video_tasks.render_job_id`.
- `public_video_links.video_task_id` -> `video_tasks._id`, but the route is not included.

Missing index concerns:

- `users.username`, `users.email`
- `customers.distributed_id`
- `customers.linked_company_id`
- `customers.linked_company_id + email`
- `templates.company_id + status`
- `media.company_id`, `media.template_id`
- `video_tasks.company_id`, `template_id`, `customer_id`, `render_job_id`
- `render_jobs.job_id`
- `public_video_links.token`

No soft-delete convention is implemented. Delete endpoints physically remove documents and media folders.

## Incomplete Features

- Admin role: `app/routes/admin.py` expects `role: "admin"`, but `ALLOWED_ROLES` only allows superadmin/company/customer.
- Public video links: `app/routes/public_video.py` and related models exist, but the router is not included in `app/main.py`.
- Forgot-password: endpoint is superadmin reset, not email-based recovery.
- Persistent logout: token blacklist is process-local memory.
- S3/object storage: env comments exist, but implementation is local filesystem only.
- Frontend integration: cannot be verified from this checkout.
- Automated test suite: mostly manual scripts; no pytest structure.
- Queue strategy: previews use an in-memory API queue while task generation uses Celery.

## Unused Code Candidates

FILE/PATH: `app/routes/public_video.py`
ITEM: Tokenized public video link router.
CURRENT USAGE: Not included in `app/main.py`.
EVIDENCE: Registered route dump does not include `/public-video/*`; `app/main.py` imports no `public_video`.
RISK OF REMOVAL: Medium; external code may expect this once wired.
RECOMMENDATION: PROBABLY UNUSED - VERIFY FIRST.

FILE/PATH: `app/services/v_renderer.py`
ITEM: Older renderer implementation.
CURRENT USAGE: No active route imports it.
EVIDENCE: Active routes import `app.services.video_renderer`.
RISK OF REMOVAL: Medium; may be a manual fallback/debug reference.
RECOMMENDATION: PROBABLY UNUSED - VERIFY FIRST.

FILE/PATH: `app/services/media_service.py`
ITEM: Alternate media save helper.
CURRENT USAGE: No active route imports it.
EVIDENCE: Active upload route uses `app.services.storage.save_upload_file`.
RISK OF REMOVAL: Low/Medium.
RECOMMENDATION: PROBABLY UNUSED - VERIFY FIRST.

FILE/PATH: `app/models/bulk_task.py`, `app/models/bulk_task_customer_model.py`
ITEM: Bulk task schemas.
CURRENT USAGE: Not imported by active routes.
EVIDENCE: Search only finds model definitions.
RISK OF REMOVAL: Medium; may represent planned bulk-render feature.
RECOMMENDATION: FUTURE/PLACEHOLDER.

FILE/PATH: `app/models/public_link_model.py`, `app/models/public_video_link_model.py`
ITEM: Public link schemas with overlapping class names.
CURRENT USAGE: Not imported by active routes.
EVIDENCE: Active public video route uses raw dicts and is not included.
RISK OF REMOVAL: Medium.
RECOMMENDATION: PROBABLY UNUSED - VERIFY FIRST.

FILE/PATH: root `repro_ffmpeg.py`, `repro_path.py`, `verify_fix.py`, `verify_output.mp4`, `repro_output.mp4`
ITEM: Debug/reproduction artifacts.
CURRENT USAGE: Not part of app startup.
EVIDENCE: Root manual scripts; `verify_fix.py` imports missing `FONT`.
RISK OF REMOVAL: Low if no developer relies on them.
RECOMMENDATION: PROBABLY UNUSED - VERIFY FIRST.

FILE/PATH: `media/text_*.txt`, `media/render_jobs/*/output.*`, root preview/probe media.
ITEM: Generated render artifacts.
CURRENT USAGE: Runtime data, not source code.
EVIDENCE: 656 files in `media/`, about 366 MB.
RISK OF REMOVAL: High if users need existing outputs.
RECOMMENDATION: UNKNOWN; create retention/export policy before cleanup.

## Duplicate Code

- Placeholder resolution exists in `app/utils/placeholders.py`, `app/routes/template.py`, and `app/routes/public_templates.py`.
- Company email hydration is duplicated in `template.py`, `public_templates.py`, and `video_task.py`.
- Mongo serialization helpers appear in multiple routes.
- Template preview/download logic is duplicated across private and public route modules.
- Video generation concepts are split across `/video-task/*`, `/tasks/*`, `/templates/*/preview`, and `/public/templates/*`.

## Technical Debt

- Large route/service files are hard to reason about.
- Many endpoints accept raw `dict`, reducing validation and API clarity.
- Mixed ObjectId/string references increase query bugs.
- Debug `print()` statements are scattered through startup, DB connection, routes, storage, and renderer.
- `voise_over.py` is likely a misspelling of `voice_over.py`.
- Prior README contained hardcoded local paths and minimal operational guidance.

## Security Findings

CRITICAL:

- `.env.prod` contains real-looking MongoDB credentials and JWT secret. Values are not repeated here. Rotate immediately if valid.
- Startup creates a fixed superadmin email/password in `app/main.py`.
- `/auth/register` accepts caller-supplied `role`.
- `/api/public/media/templates` allows unauthenticated uploads when `company_id` and `template_id` are known.
- `/render-jobs/{job_id}` and `/render-jobs/{job_id}/download` are public.

HIGH:

- Several template/customer/company endpoints lack ownership checks or authentication.
- Public render/preview endpoints can trigger expensive CPU/GPU/FFmpeg work.
- Token blacklist is in memory and not shared across workers.
- CI workflow echoes deployment context unnecessarily.

MEDIUM:

- File validation relies heavily on extension/content-type, not robust content inspection or size limits.
- DB connection string is printed at startup.
- Full user/profile payloads are printed in auth/customer routes.
- CORS origins are hardcoded.

LOW:

- Public `/kokoro/health` exposes whether CUDA is available.
- Default local `SECRET_KEY` in `.env.example` should be replaced with a placeholder.

## Performance Findings

HIGH:

- Public preview/download/TTS endpoints can exhaust CPU/GPU/disk without rate limits.
- In-memory render queue requires a single API worker and loses job state on restart.

MEDIUM:

- Company list performs per-company user lookups.
- Many list endpoints lack pagination.
- Media/render artifacts accumulate without retention policy.
- TTS model loading can make first request slow; warmup exists but is not called.

LOW:

- Public template endpoints may return large `template_json` documents.

## Dependency Findings

- `Django==5.2.4` appears in `requirements.txt`, but no Django usage was found.
- `selenium`, Trio-related packages, and PySocks appear unused by application code.
- `typing` is listed even though it is part of Python.
- Kokoro/Torch dependencies are heavy and should be isolated if TTS is optional.

Do not remove dependencies without runtime tests and deployment confirmation.

## Production Risks

- Secrets and fixed credentials create immediate account/database compromise risk.
- Local media storage may be lost on ephemeral deployment platforms.
- Missing Mongo indexes will become slow as data grows.
- Mixed ID types can cause missing records and failed deletes.
- Public render endpoints can create denial-of-service conditions.
- No centralized migrations/index management.
- No comprehensive automated tests.

## Verification Performed

- `python -m compileall -q app test_render_queue_fifo.py test_render.py verify_fix.py fix_media_paths.py repro_ffmpeg.py repro_path.py` passed.
- `python test_render_queue_fifo.py` passed and preserved FIFO processing/completion order.
- Importing `app.main` registered 61 routes and confirmed included routers.

## Step 2 Recommendation

Start with production safety before cleanup:

1. Rotate/remove committed secrets and delete fixed superadmin credentials.
2. Lock down public role registration, public uploads, render-job downloads, and ownership checks.
3. Fix duplicate/missing routes: `GET /templates/`, `public_video.py`, and legacy `/video-task` overlap.
4. Add schemas and an index/migration strategy.
5. Only then clean up legacy files/dependencies and generated media artifacts.
