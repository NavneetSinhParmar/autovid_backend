# Production concurrency audit and implementation plan

Audit date: 2026-10-11. Scope: backend only. No production connection is available.

## Architecture inspected

Inspected `app/main.py`, environment/settings/errors, rendering and upload routes
(`task`, `video_task`, `template`, `public_templates`, `public`, `media`, `company`,
`customer`, `campaign`, `voise_over`, `render_jobs`, `monitoring`), job models and
MongoDB indexes; `render_queue`, `celery_app`, `video_worker`, `video_renderer`,
legacy `v_renderer`, `render_helper`, `output_validator`, `media_validator`,
`media_upload`, `media_service`, `storage`, `public_media`, `kokoro_tts`, database
connections; requirements, Dockerfile, Procfile, example environment, README,
existing tests and benchmark/load scripts. Frontend inventory was inspected only
to establish project boundaries. Secret environment files were not printed.

Requests normally persist jobs and return 202. MongoDB tracks status; Redis
dispatches independent video/image/TTS/campaign/maintenance queues. Workers
atomically claim QUEUED jobs. Outputs have job-specific paths and owner/capability
downloads. Local development additionally has process-local thread pools and a
legacy FIFO queue. These are preserved.

## Findings before changes

* Default video pool and documented worker command allow 100 tasks; no global
  FFmpeg process gate exists. Multiple workers multiply concurrency.
* FFmpeg timeout is explicitly None. Probe timeout is absent in renderer.
  Long-running jobs can keep resources indefinitely.
* Decoder threads are set only before the first input; filter and encoder thread
  controls are partially present. Output-size composition, still reuse, 30 FPS,
  veryfast/CRF22, H.264/AAC and 720p already work and should be preserved.
* Stale heartbeat recovery can overlap a still-running renderer. Atomic job claims
  alone do not protect output files against an orphaned FFmpeg child.
* Mongo insertion and Redis publication are not transactional. Queued jobs can be
  stranded on a crash between these operations. Idempotency pre-check races with
  the existing unique index; duplicate insertion should return the existing job.
* Video upload validation reads up to 250 MB into bytes then copies to a probe
  file. Four slots per API process can consume roughly 1 GB before renderer/TTS
  allocations. Logo routes read files again after validation.
* SVG is not accepted; Pillow is declared but runtime import failure is mislabeled
  as missing installation even if native dependencies failed to load.
* Font cache writes directly to a shared final filename; readers can see partial
  files. Remote media may be downloaded/probed repeatedly by FFmpeg.
* Progress is normally 5 then 100; no FFmpeg time-based updates. Queue position
  is not reliable across routed queues, reservations, retries and workers.
* Local executors and legacy in-memory job dictionaries have no durable broker
  semantics. Production must explicitly select Celery.
* No actual systemd units are in this workspace. RAM, swap, cgroup limits and
  server benchmark results are unknown. Ten cannot be recommended as measured safe.

## Focused implementation plan

1. Conservative two-render default, target settings capped at ten, independent
   FFmpeg filter threads and finite duration/probe/render limits.
2. Host-wide advisory file locks for all application FFmpeg processes, memory
   admission check and job execution locks. Linux children inherit lock descriptors
   so parent crashes cannot free a slot or job while FFmpeg is still alive. The
   supported deployment is multiple workers on ONE Linux host using one lock
   directory; multi-host operation requires a different coordinator.
3. Recover stale processing jobs only when their execution lock is free; reconcile
   unpublished queued jobs; retain MongoDB claims and bounded retries. Queue
   admission is serialized across API/campaign workers using the same host locks.
4. Stream video uploads to disk, safely rasterize SVG without external references,
   make font cache publication atomic, and persist FFmpeg progress.
5. Supply systemd units, non-root worker launcher, safe restart instructions,
   repeatable opt-in load/throughput tooling and automated regression tests.

No endpoint removal, frontend change, database deletion, queue purge, production
load generation or deployment is authorized by this implementation plan itself.
The user requested local implementation and deployment artifacts; proceed with
those. Preserve secret files and completed media.
