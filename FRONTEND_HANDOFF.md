# AutoVid Frontend Integration Handoff

Reviewed against backend source and the supplied frontend checklist on 2026-09-28.
This is a source-level contract review, not a live integration certification. The frontend repository was not inspected. Existing backend task checkmarks are not proof that production acceptance tests passed.

## 1. Required implementation order

1. Secure NextAuth/session-backed proxy routes and remove embedded secrets.
2. Centralize API calls, per-endpoint response adapters, errors and authentication.
3. Fix protected media previews and downloads.
4. Integrate asynchronous image/video/TTS jobs.
5. Switch lists to server pagination/search/filter/sort where available.
6. Integrate supported campaign creation, status and job history.
7. Preserve editor JSON and verify rendering of fonts, images, logos and sound.
8. Run frontend build/type checks and staging end-to-end tests.

## 2. Base URL, authentication and errors

- Backend routes do NOT share a universal `/api` prefix. Use paths below exactly. Next.js `/api/*` proxies are frontend-owned routes.
- `POST /auth/login`: JSON `{ "username": "...", "password": "..." }`, or `email` instead of `username`. Response includes `access_token` and `role`; construct the Bearer authorization header in your client.
- `GET /auth/profile`: bearer-authenticated profile. Distinguish user IDs from company/customer profile IDs.
- `POST /auth/logout`: bearer-authenticated. Also clear NextAuth session, query caches, editor state and protected blob URLs.
- No refresh-token endpoint is implemented. On expired authentication, preserve safe navigation intent and request sign-in; do not loop refresh requests.
- Backend logout revocation currently uses process-local memory. Durable multi-instance revocation remains a backend dependency.
- Public registration creates only customers. Never offer company/superadmin self-registration through `/auth/register`.
- Use `Authorization: Bearer <token>` for private calls. With a Next.js proxy, retrieve the backend token from the validated server session.
- Configure backend CORS for the deployed frontend origin. Do not put database, JWT signing or provider secrets in `NEXT_PUBLIC_*` variables.
- Standard handled errors use `{ error: { code, message, details? }, request_id, timestamp }`. Some framework/proxy errors may still use `{detail: ...}`; support both.
- Handle 400/401/403/404/409/413/422/429/500/503 and network timeout distinctly. Show safe messages and a request ID, never stack traces.
- Do not automatically retry POST render/upload/campaign requests after a timeout: the server may already have accepted them. Request-level deduplication is not consistently exposed.
- Success payloads are not universally `{data: ...}`. Normalize each endpoint in the frontend API layer.

## 3. API mapping

| UI feature | Backend endpoint | Contract / limitation |
| --- | --- | --- |
| Companies | `GET/POST /company/`, `GET/PATCH/DELETE /company/{id}` | Create/update use form fields; company administration is privileged. |
| Customers | `GET/POST /customer/`, `GET/PATCH/DELETE /customer/{id}` | Create supports existing JSON/form handling; update uses form fields. |
| Customer import | `POST /customer/bulk-upload` | Separate from campaign import. Confirm required multipart fields in `/docs`. |
| Categories | `GET/POST /category/`, `GET/PATCH/DELETE /category/{id}` | JSON create/update; scoped to company. |
| Templates | `GET/POST /templates/`, `GET/PATCH/DELETE /templates/{id}` | Company-owned; JSON create/update. |
| Media library | `GET /media-api` | Paginated `items`; superadmin supplies `company_id`. |
| General upload | `POST /media-api/upload` | Multipart `file`; superadmin supplies `company_id`. Response `{media: ...}`. |
| Template upload | `POST /api/public/media/templates` | Multipart `file`, `template_id`, optional privileged `company_id`. Despite its name, requires authenticated ownership. |
| Public template list | `GET /api/public/templates` | Published active templates; pagination only. |
| Public template detail | `GET /api/public/template/{id}` | Response `{template: ...}`. |
| Template preview | `POST /templates/{id}/preview` | No body required; returns 202 and job details. |
| Personalized preview | `POST /templates/{id}/preview/{customer_id}` | Handles image/video selection and dynamic TTS preparation. |
| Customer video | `POST /tasks/generate?template_id=...&customer_id=...` | IDs are query parameters; returns 202, `task_id`, `job_id`, `status`, `progress`, `status_url`. Video-specific path. |
| Public render | `POST /public/templates/{id}/preview` or `/download` | JSON `{fields: {...}, customer: {...}}`; returns 202, job details and `access_token`. |
| Job history | `GET /render-jobs` | Paginated `items`; bearer authentication. |
| Job status | `GET /render-jobs/{job_id}` | Bearer authentication or public job capability token. |
| Job result | `GET /render-jobs/{job_id}/download` | Binary response; available after COMPLETED. |
| Cancel job | `POST /render-jobs/{job_id}/cancel` | Authenticated owner; QUEUED only. PROCESSING/completed jobs return 409. |
| Voice list | `GET /kokoro/voices` | Response `{voices: [...]}`. |
| Generate speech | `POST /kokoro/tts` | JSON `{voisetext, voice, speed, company_id?}`; 202 job response. |
| Campaign list/create | `GET/POST /campaigns` | POST JSON `{name, template_id, customer_ids: [...]}`; company role. |
| Campaign import | `POST /campaigns/upload` | Multipart `name`, `template_id`, `data_file`; 202 with `campaign_id`, `status`. |
| Campaign details | `GET /campaigns/{id}` | Counters and status; owner/superadmin. |
| System monitoring | `GET /monitoring/metrics` | Superadmin only; not a company dashboard endpoint. |

Use deployed `/openapi.json` and `/docs` for exact multipart fields and schemas before wiring CRUD forms. Keep Next.js upload and voice proxies aligned with these paths; `/api/uploads`, `/api/voice-over`, and `/api/voice-over/:id` are not implemented backend endpoints.

Do not use `POST /video-task/generate` as the main render action: it creates a task record without queueing a render. Do not use `GET /templates/{id}/download/{customer_id}` for new jobs: it looks for a legacy output filename. Use the job download endpoint. The `public_video.py` router is not registered.

## 4. Pagination and table adapters

Common private-list parameters: `page=1`, `limit=50`, `search`, `sort_by`, `sort_order=asc|desc`. Maximum limit is 200. Public templates cap the limit at 100 and currently support only page/limit. `/video-task/all` is also pagination-only.

| List | Array key | Additional filters |
| --- | --- | --- |
| `/company/` | `companies` | `status`, `visibility` |
| `/customer/` | `customers` | `status`, `category` |
| `/category/` | `categories` | `status`, `company_id` for superadmin |
| `/templates/` | `templates` | `category`, `template_type`, `status` (defaults to active) |
| `/media-api` | `items` | `file_type`, `company_id` |
| `/campaigns` | `items` | `status` |
| `/render-jobs` | `items` | `status`, `campaign_id`, `job_type` |
| `/api/public/templates` | `templates` | None beyond pagination |

Each includes `page`, `limit`, `total`, `has_next`. Normalize to a frontend `Page<T>` without discarding metadata. Search resets page to 1; debounce and cancel stale requests. Only request supported sort fields: unsupported names silently fall back to the route default. AG Grid column IDs must be mapped to backend field names.

Dedicated customer/template/date filters on job history are not implemented. `search` currently searches job ID and exact customer/template IDs; it is not equivalent to independent combinable filters. Do not pretend a current-page filter searches the whole dataset.

## 5. Render and TTS state

- On 202, store `job_id` immediately. It means accepted, not completed.
- Poll `/render-jobs/{job_id}` approximately every 2-3 seconds, backing off on network errors/429. Stop on COMPLETED, FAILED or CANCELLED. Avoid one poller per table row.
- Restore known job IDs after reload; use authenticated history for reconciliation. On tab return, refresh status once before restarting normal polling.
- Render statuses: QUEUED, PROCESSING, COMPLETED, FAILED, CANCELLED. Display returned progress only. Current progress is coarse stage progress, not continuous FFmpeg progress or a reliable ETA.
- Public renders return a separate capability `access_token`. Send it as `?access_token=...` on job status and download. It is not the user's login token. Do not include it in analytics/logs or public share links unintentionally.
- Use a session-authenticated same-origin proxy for private `<img>`, `<video>`, `<audio>` and downloads, or fetch a protected result as a Blob with Authorization and create an object URL. Native media elements cannot attach your bearer header themselves.
- Revoke object URLs on replacement/unmount. Keep persisted server media references in template JSON; never save temporary blob URLs.
- For video proxy streaming, forward Range requests and preserve Content-Type, Content-Length, Content-Range, Accept-Ranges and 206 behavior. Avoid buffering large videos unnecessarily.
- Do not send bearer tokens to arbitrary remote media URLs. Resolve only trusted backend paths through the authenticated proxy.
- Enable cancel only for authenticated queued jobs. There is no public-token cancellation or job retry endpoint. A deliberate user-confirmed resubmit creates a new job.
- TTS uses the same job status/download flow. Request key is spelled `voisetext`; speed is 0.5-2.0. Limit text to 5,000 characters in UI because backend truncates longer text. Insert audio into timeline only after completion.
- Clear old preview state when submitting a new job; associate completion with the correct editor revision to prevent a slow old response overwriting a new preview.

## 6. Upload and editor compatibility

Backend defaults (deployment configuration can override these):

| Media | Formats | Default constraints |
| --- | --- | --- |
| Image | JPG/JPEG/PNG/WebP | 10 MiB; width and height <=8192 |
| Video source | MP4/MOV/WebM | 250 MiB; <=300 seconds |
| Audio | MP3/WAV/M4A/AAC/OGG | 25 MiB; <=600 seconds |
| Generated video | MP4 | <=60 seconds; H.264 + AAC when audio exists; max 1280x720; no unnecessary upscaling |

- SVG is rejected. Do not advertise it as supported.
- No upload-constraints endpoint exists yet. Keep UI limits in one deployment configuration shared with backend settings; backend validation remains authoritative.
- Use `VIDEO_TOO_LONG`, not only the older task.md name `VIDEO_DURATION_EXCEEDED`. Also handle FILE_TOO_LARGE, INVALID_MEDIA_TYPE, INVALID_IMAGE, INVALID_VIDEO, UNSUPPORTED_FORMAT and IMAGE_DIMENSIONS_EXCEEDED.
- Distinguish source duration from generated timeline duration. A five-minute source does not permit a five-minute personalized output; trim/use a timeline <=60 seconds.
- Browser preview support can differ from backend codec support. A browser metadata/preview failure must not be presented as definitive server corruption.
- Preserve full template_json, track IDs/order, timing/trim, customer-field metadata, font family/weight, text styling, image crop/position, logo aspect ratio, audio volume and dynamic voice metadata through load/save.
- Template types accepted by create/update: `video`, `image`, `img`. New templates default to private (`public: false`).
- PATCH currently excludes null values; clearing a saved media field with null is not supported reliably. Treat that as a backend contract gap.
- General upload returns a relative file_url; template upload may return `./media/...`. Normalize these for display in one helper without rewriting stored editor data blindly.
- Validate before inserting uploaded media into the editor. Cancel/retry must not remove an existing working asset or corrupt undo/redo history.
- Verify public templates can load every referenced asset: arbitrary company media URLs are protected, even if referenced by a public template. Public-safe asset publishing needs backend verification.

## 7. Campaign UI: available and pending

Available: create with existing customer IDs or CSV/XLSX, list/details, polling counters, and campaign job history via `/render-jobs?campaign_id=...`.

Import requires a reference column: `customer_id`, `id`, `distributed_id`, or `email`. It resolves existing company customers; it does not create new customers from arbitrary spreadsheet rows. Default upload cap is 10 MiB and processing cap is 5,000 rows. Enforce that row cap in UI; current worker truncates excess rows. Use canonical lowercase column names.

Current counter names are `total`, `queued`, `processing`, `completed`, `failed`, `progress`, not `total_jobs` or `progress_percentage`. Do not invent a cancelled count when absent.

Backend dependencies still pending:

- Separate validate/preview endpoint with valid/invalid rows and row-level errors before confirmation.
- Campaign cancellation and retry-failed endpoints.
- Reliable cancelled/partial-completion reporting and counter reconciliation.
- Failed-record export endpoint (a current-page export is not a full-campaign export).
- Campaign request deduplication: an idempotency_key model field exists, but the creation route does not use it.
- Robust handling of invalid customer references rather than silently skipping rows.

Keep unsupported actions disabled or out of the released UI until their backend contracts exist.

## 8. Missing checklist points to add

- [ ] Separate accepted render submission from completed output, including TTS.
- [ ] Implement protected media preview/download and Range forwarding.
- [ ] Retain public job capability securely and restore polling after refresh.
- [ ] Handle coarse progress, terminal states, stale results and polling cleanup.
- [ ] Map list array keys, query names and supported sort fields per endpoint.
- [ ] Include company/user identity in query keys; clear caches on logout/company switch.
- [ ] Disable duplicate submits; reconcile uncertain POST results without automatic resubmission.
- [ ] Separate 300-second source limit from 60-second generated timeline limit.
- [ ] Preserve persistent media references and revoke temporary blob URLs.
- [ ] Add audio upload constraints and asynchronous TTS handling.
- [ ] Handle unsupported browser codecs without mislabeling backend validity.
- [ ] Treat public publishing and PATCH-null clearing as explicit integration tests.
- [ ] Feature-gate backend-dependent campaign validation/retry/cancel/export and history date filters.
- [ ] Test proxy session expiry while downloading/uploading and during background polling.
- [ ] Verify font loading/fallback, logo placement/crop, captions, sound, mute/volume, trim and dynamic TTS in actual generated files.
- [ ] Test Company A/B cache separation and direct endpoint access, not only hidden buttons.
- [ ] Test 429 backoff, 503 queue failure, refresh recovery and download before completion.

## 9. Acceptance and remaining backend work

The supplied UI checklist covers most frontend work. Its items cannot be marked complete without inspecting and testing the frontend project. The backend task.md also has unfinished items; comprehensive isolation, render fidelity, live queue recovery and load readiness still need integration verification.

Existing source gaps include unauthenticated private/combined download-counter mutation routes in public_templates.py, process-local logout revocation, mixed success payloads, legacy download behavior and incomplete campaign controls. Do not call those counter mutation routes from new UI; backend authorization must be fixed independently.

Next.js Pexels/transcription proxies and their provider contracts are outside this backend. Verify those in the frontend project. No backend transcription endpoint was identified.

Before release, test with real MongoDB/Redis/workers/FFmpeg/Kokoro: login, company/customer/template CRUD, upload, image/video preview, TTS, secured download, queued cancellation, campaign import and pagination. Compare editor preview against generated output using realistic fonts/logos/sound. Then run frontend typecheck/build and Playwright desktop/mobile tests.

5K traffic or 100-500 concurrent submissions are not certified by this handoff. Actual staged load and media throughput tests remain deployment gates.
