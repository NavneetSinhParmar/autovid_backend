# Validation results — 2026-10-11

Implementation was made locally on Windows. No production deployment, production
load test, queue purge or database migration was performed.

## Measured local benchmark

Raw report: [benchmark-local.json](benchmark-local.json). Machine: 12 logical CPU
threads, 16,108 MB RAM, Windows 10 build 26200. Fixture: 15-second 1280x720 video
with PNG background/logo overlays, text and sine-wave audio, H.264 veryfast/CRF22,
one encoder/filter thread. It is lighter than many real customer templates.

| Measurement | Local result |
| --- | ---: |
| Submitted / completed / failed | 2 / 2 / 0 |
| Actual overlapping FFmpeg processes | 2 |
| Average render time | 2.395 s |
| Maximum render time | 2.892 s |
| Batch render wall time | 3.156 s |
| Combined peak sampled FFmpeg RSS | 194.879 MB |
| Average / peak sampled host CPU | 23.88% / 47.2% |
| Minimum sampled available host RAM | 4,268.438 MB |
| Peak host swap already in use | 783.848 MB |
| Samples | 21 |

These are sampled host CPU/RAM values, not exclusively render CPU. Swap usage
includes existing applications; the report does not establish render-caused swap
growth. Exact process overlap is reconstructed from child start/end events;
resource peaks are sampled, so can miss shorter spikes. Python/Celery/TTS/MongoDB
memory is not included in FFmpeg RSS.

An earlier sandboxed observation could not measure processes reliably. The
retained report was rerun with process visibility, explicitly reports its scope
as benchmark children, and confirms two overlapping FFmpeg processes.

## Automated checks

Final run: **65 tests, 63 passed, 2 skipped**, plus the existing five-job FIFO
regression passed. Python compilation and Git whitespace checks passed.

Standard-library unit and real FFmpeg pipeline tests cover queue admission races,
100 mixed render submissions, bounded uploads, tenant-scoped cached-file reuse,
file isolation, global process locking, low memory, retries, duplicate locking,
crash recovery, dispatch reconciliation, failed processes, timeout cleanup,
time-based progress, preserved outputs, JPEG/PNG and malicious SVG rejection,
remote-asset streaming/reuse, geometry/audio and simultaneous image/video rendering.

Two tests require Linux/native Cairo and are skipped locally: parent-crash lock
inheritance and real SVG rasterization. CairoSVG Python packages were installed
in a project-local test dependency folder; native Cairo is absent on this Windows
machine. Docker and Linux setup explicitly install libcairo2. This is a runtime
dependency issue separate from Pillow, which already imported successfully here.

## Unmeasured production work

The 8-core Linux server, current systemd units, actual RAM/cgroups, Redis durability,
representative customer templates and live multi-worker crash behavior were not
accessible. No real API burst benchmarks were run against production. The supplied
script supports 10/30/70/100 requests and separately gated 2/4/6/8/10 render stages.

Keep concurrency at **two provisionally**; this is not a measured server capacity
recommendation. Increase only after server-specific tests meet the conditions in
[deploy/README.md](deploy/README.md). Ten is implemented as an upper target,
not validated capacity. Multi-host coordination and stronger campaign counter
transactions remain architectural recommendations, not implemented guarantees.

## Modified and added backend files

* Configuration/dependencies: `app/core/settings.py`, `app/services/celery_app.py`,
  `requirements.txt`, `Dockerfile`, `.env.example`, `Procfile`, `.gitignore`.
* Execution/queue: `app/services/render_resources.py`, `ffmpeg_process.py`,
  `render_queue.py`, `video_renderer.py`, `v_renderer.py`, `output_validator.py`,
  `kokoro_tts.py`, `app/worker/video_worker.py`.
* Upload/storage: `app/services/svg_raster.py`, `media_validator.py`,
  `media_upload.py`, `storage.py`, `app/routes/customer.py`.
* API details: `app/routes/task.py` preserves queue-full errors;
  `app/routes/render_jobs.py` excludes capability hashes from list results.
  `app/routes/campaign.py` dispatches broker I/O off the API event loop.
* Tools: `scripts/run_worker.py`, `resource_metrics.py`, `load_render_queue.py`,
  `benchmark_concurrency.py`; `deploy/*.service`, `capacity.env.example`, README.
* Tests: `tests/test_render_capacity.py`, `test_worker_recovery.py`,
  `test_concurrent_media.py`, `test_security_and_validation.py`, `test_video_pipeline.py`.
* Documentation/results: `README.md`, `CONCURRENCY_AUDIT.md`, this document and
  `benchmark-local.json`.

No frontend code or secret environment files were modified. Existing MongoDB
collections/indexes and endpoints were preserved; job/campaign records only gain
additive fields, including user_id and campaign expansion_pending.
