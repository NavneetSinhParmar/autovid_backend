# Deployment, restart and scaling

This implementation supports multiple prefork workers on **one Linux host**. Every
API, worker and maintenance service must share the same RENDER_LOCK_DIR and media
filesystem. Do not run a second host/container with a private lock directory.
Separate Docker containers need the SAME bind-mounted lock directory; network
filesystem flock behavior must be validated before using it. A multi-host Redis
lease alone is insufficient: expired leases can overlap live FFmpeg processes.

## Current defaults and target

Start with two active FFmpeg processes and two video worker children, one encoder
thread and one filter thread per process. Two is a conservative starting setting,
not a measured recommendation for your 8-core server. The process limit also
counts image renders and TTS encodes, keeping total application FFmpeg processes
at or below the limit. These queues have their own consumers, but may wait for the
shared budget. Duplicate deliveries and memory/capacity waits retry without
spending the job's failure budget. Execution locks prevent concurrent duplicates;
Celery delivery remains at-least-once, not transactional exactly-once.

After representative tests establish capacity, the target is:

```env
CELERY_RENDER_CONCURRENCY=10
MAX_CONCURRENT_VIDEO_RENDERS=10
FFMPEG_THREADS=1
FFMPEG_FILTER_THREADS=1
CELERY_WORKER_PREFETCH_MULTIPLIER=1
```

Both concurrency settings are capped at ten. CELERY_RENDER_CONCURRENCY takes
precedence over legacy VIDEO_WORKER_CONCURRENCY. The launcher passes the value
explicitly to Celery; environment variables alone cannot override a hardcoded
service --concurrency argument. All workers must use identical slot limits. A
configuration reduction requires a warm stop of all render consumers, waiting for
children to exit, then a coordinated restart. Never unlink or replace live lock
files: doing so creates separate lock domains and defeats concurrency protection.

Memory admission uses measured available host/cgroup RAM plus a configurable
reserve and conservative per-process estimate. Calibrate RENDER_MEMORY_PER_PROCESS_MB
above measured representative peak usage. This estimate is not a hard memory
allocation guarantee. Celery's per-child memory setting recycles a child AFTER a
task; it cannot prevent a task's peak allocation. TTS/Torch has its own potentially
large memory footprint; keep its concurrency at one initially. Torch/Kokoro now
load lazily in TTS execution rather than all video/image worker startup.

Queue admission counts all QUEUED/PROCESSING jobs atomically across cooperating
host processes. At 500 pending jobs, new direct submissions return 429; existing
campaign expansion pauses and resumes as jobs finish. No accepted queued job is
discarded. No reliable exact queue-position claim is made across routed queues.
Status polling uses existing endpoints and does not wait for rendering.

## Inspect the real services first

The repository had no actual systemd units. These are replacement templates,
not a verified copy of the running service. Inspect locally and preserve any
needed reverse-proxy, port, environment or service-account differences:

```bash
sudo systemctl cat autovid_backend.service autovid_celery.service
sudo systemctl show autovid_backend autovid_celery -p User -p WorkingDirectory -p ExecStart -p KillMode -p TimeoutStopUSec
systemctl list-units 'autovid*'
free -h
lscpu
df -h /var/www/autovid_backend/media
redis-cli CONFIG GET appendonly
redis-cli CONFIG GET maxmemory-policy
```

Do not paste secret environment values into tickets. Configure Redis durability
(AOF/backups) and noeviction through your established operations procedure. Do
not use FLUSHDB, FLUSHALL or celery purge during deployment.

## Linux installation commands

Run after putting the revised BACKEND files in /var/www/autovid_backend. Back up
existing units and application files using your release/backup process before
replacement. Keep .env, .env.local, MongoDB data, Redis and media in place.

```bash
cd /var/www/autovid_backend
sudo apt-get update
sudo apt-get install -y python3.11-venv ffmpeg libcairo2 fontconfig fonts-dejavu-core
id autovid || sudo useradd --system --user-group --home-dir /var/lib/autovid --create-home --shell /usr/sbin/nologin autovid
test -x .venv/bin/python || python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'import sys, PIL, cairosvg, psutil, celery; print(sys.executable); print(PIL.__version__, cairosvg.__version__, celery.__version__)'
sudo install -d -o autovid -g autovid -m 0750 /var/lib/autovid /var/lib/autovid/render_locks
sudo install -d -o autovid -g autovid -m 0750 /var/www/autovid_backend/media
sudo chown -R autovid:autovid /var/www/autovid_backend/media
sudo chgrp autovid /var/www/autovid_backend/.env
sudo chmod 0640 /var/www/autovid_backend/.env
test -f deploy/capacity.env || cp deploy/capacity.env.example deploy/capacity.env
sudo chgrp autovid deploy/capacity.env
sudo chmod 0640 deploy/capacity.env
sudo -u autovid test -r /var/www/autovid_backend/.env
sudo -u autovid test -x /var/www/autovid_backend/.venv/bin/python
sudo -u autovid test -r /var/www/autovid_backend/app/main.py
sudo -u autovid test -w /var/www/autovid_backend/media
sudo -u autovid test -w /var/lib/autovid/render_locks
```

Review deploy/capacity.env; initial values intentionally remain two. Ensure code,
fonts and venv are readable by autovid; the source tree does not need to be owned
by the service account. If the current .env path differs, adjust BOTH unit
EnvironmentFile entries; do not create placeholder secrets or overwrite .env.

## Warm restart with retained queues

The FIRST rollout must drain ALL old workers because they do not honor the new
locks. Stop submissions briefly at your proxy, let active jobs finish, and stop
all existing render/image/TTS/campaign consumers and old beat instances. Inspect
the actual unit list above and include your existing auxiliary service names.
Existing old units may have a short systemd stop timeout: set a temporary drop-in
TimeoutStopSec=1800 and SendSIGKILL=no before stopping them. Celery handles TERM
as warm shutdown. Do not force-kill children to accelerate deployment.

For subsequent deployments with these units installed:

```bash
sudo systemctl stop autovid_aux@beat.service
sudo systemctl stop autovid_celery.service autovid_aux@render_image.service autovid_aux@tts.service 'autovid_aux@campaigns,maintenance.service'
systemctl is-active autovid_celery.service autovid_aux@render_image.service autovid_aux@tts.service 'autovid_aux@campaigns,maintenance.service'
pgrep -u autovid -a ffmpeg
```

Proceed only when services are inactive and application FFmpeg children have
exited. A stop timeout with SendSIGKILL=no requires investigating the specific
stuck invocation; don't start another worker while the old one remains alive.
The first rollout must also verify no legacy workers remain under another user.

```bash
sudo install -m 0644 deploy/autovid_backend.service /etc/systemd/system/autovid_backend.service
sudo install -m 0644 deploy/autovid_celery.service /etc/systemd/system/autovid_celery.service
sudo install -m 0644 deploy/autovid_aux@.service /etc/systemd/system/autovid_aux@.service
sudo systemctl daemon-reload
sudo systemctl enable autovid_backend autovid_celery autovid_aux@render_image autovid_aux@tts 'autovid_aux@campaigns,maintenance' autovid_aux@beat
sudo systemctl restart autovid_backend
sudo systemctl start autovid_celery autovid_aux@render_image autovid_aux@tts 'autovid_aux@campaigns,maintenance' autovid_aux@beat
sudo systemctl status autovid_backend autovid_celery --no-pager
sudo journalctl -u autovid_celery -n 50 --no-pager
```

Exactly one beat instance should run. Recovery examines heartbeats but first
obtains the job lock; active/orphaned FFmpeg prevents premature recovery. Queued
records from interrupted Redis publication are republished after the stale window
(default 900 seconds). Redis visibility timeout exceeds normal render timeout.
Service restart never clears queue keys or media. A failure between MongoDB and
Redis can return 503 with a job_id while leaving a recoverable QUEUED job: poll
that job before resubmitting to avoid creating another request.

## Staging checks and benchmarks

Run tests with isolated test configuration, not production database credentials:

```bash
MONGO_URL=mongodb://127.0.0.1:27017 DATABASE_NAME=autovid_unit_tests SECRET_KEY=isolated-unit-test-secret-key-at-least-32-bytes MAX_SOURCE_VIDEO_SECONDS=1800 MAX_OUTPUT_VIDEO_SECONDS=900 .venv/bin/python -m unittest discover -s tests -v
```

The standard tests mock DB operations and use disposable local folders. Linux
must pass the inherited-lock crash test and the real Cairo SVG conversion test.
Then run live MongoDB/Redis/Celery integration checks on an isolated deployment;
those were NOT run against your production server here.

Start with the two-render benchmark. Run under the service account on a quiet
staging host with sufficient process visibility:

```bash
.venv/bin/python scripts/benchmark_concurrency.py --execute --counts 2 --validated-max 2 --seconds 30 --output benchmark-2.json
.venv/bin/python scripts/benchmark_concurrency.py --execute --counts 4 --validated-max 4 --seconds 30 --output benchmark-4.json
.venv/bin/python scripts/benchmark_concurrency.py --execute --counts 6 --validated-max 6 --seconds 30 --output benchmark-6.json
.venv/bin/python scripts/benchmark_concurrency.py --execute --counts 8 --validated-max 8 --seconds 30 --output benchmark-8.json
.venv/bin/python scripts/benchmark_concurrency.py --execute --counts 10 --validated-max 10 --seconds 30 --output benchmark-10.json
```

Each command is a separate stage; review its results BEFORE authorizing the next.
The script refuses stages above --validated-max and skips when measured free RAM
is below the configured estimate/reserve. It creates independent synthetic 720p
overlay/text/audio fixtures, isolated lock directories and output folders; it
does not modify templates or queue jobs. Keep outputs until inspected. Also test
actual representative templates using scripts/benchmark_video.py, especially
video backgrounds, many overlays, custom fonts and dynamic TTS; synthetic still
backgrounds underrepresent expensive video decoding and filter graphs.

Set staging capacity to the selected safe level, restart consumers, set ACCESS_TOKEN
in your shell without committing it, then measure queuing with real templates:

```bash
.venv/bin/python scripts/load_render_queue.py --execute --base-url http://127.0.0.1:8000 --template-id YOUR_STAGING_TEMPLATE_ID --counts 10,30,70,100 --output load-results.json
```

It reports acceptance/rejections, API latency, completed/failed/unfinished jobs,
average/max render time, waiting time, CPU, RAM, swap and sampled host FFmpeg
count. Run it ON the worker host for useful resource data. Rate limits remain
enabled; adjust staging limits intentionally if earlier runs consume their quota.
Do not change production rate limits just to get an attractive benchmark.

For a production limit choose the highest REPEATED stage with zero render
failures, observed FFmpeg count within the budget, sufficient free RAM for the
API/DB/Redis/TTS, no growing swap, and acceptable queue wait/p95 API latency.
Keep CPU headroom (for example below 80% sustained) for the other services. Ten
one-thread encoders can saturate an 8-core host before filters/decoders/TTS are
counted; two remains the provisional setting until server results exist.

## Remaining boundaries

* No 8-core Linux resource measurements or real systemd configuration were
  available. Do not infer safe ten-render capacity from local Windows timings.
* Lock correctness assumes cooperating services on one host, stable lock files,
  identical slot configuration and no manual FFmpeg commands bypassing the runner.
* The Windows fallback is for development; Linux inherited descriptors provide
  the parent-crash protection. Windows does not provide that production guarantee.
* FFmpeg elapsed timeout is enforced by its live parent. After abrupt parent
  death the child retains its locks until exit; do not reclaim those slots by TTL.
  Investigate a stuck orphan by its own PID, never terminate unrelated renders.
* Worker memory recycling is not a peak-RAM hard limit. SVG conversion rejects
  external resources and caps raster size, but complex SVG paths can still be
  expensive. Cairo/native library behavior must be tested on the deployment.
* Remote assets are streamed once per job to bounded temporary files, not cached
  across users/jobs. Signed URLs can expire; REMOTE_ASSET_CACHE=false retains the
  legacy FFmpeg URL path for streaming sources. Font cache is published atomically.
* Campaign counters and job records span multiple MongoDB operations. A crash
  between insertion and counter update can require counter reconciliation; no
  multi-document transactional exactly-once claim is made.
* Completed output retention remains unchanged. Legacy in-memory job dictionaries
  are not durable and can grow; use Celery in production.

References: [Celery worker shutdown](https://docs.celeryq.dev/en/stable/userguide/workers.html),
[late acknowledgement and idempotency](https://docs.celeryq.dev/en/stable/userguide/tasks.html).
