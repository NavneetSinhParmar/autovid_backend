# Image generation and repeated status requests

The frontend previously requested status immediately after submission, then
slept 2.5 seconds before checking again. This added visible delay even when
FFmpeg finished in less than 0.1 seconds. Those requests were status polls, not
new render executions.

The shared frontend render helper now requests `wait_seconds=15`. The backend
holds that request asynchronously and returns as soon as it sees a terminal
status; fifteen seconds is the maximum hold time, not an imposed delay. It checks
MongoDB every 0.2 seconds while waiting. When a job is still pending at fifteen
seconds the frontend opens another waiting request. Completed submissions skip
the status request entirely. Downloads propagate cancellation. Existing callers
without wait_seconds retain the original immediate status API.

The public image form starts uploading when a file is selected, reuses the same
upload promise when Generate is clicked, and avoids re-uploading that file when
only text changes. Multiple fields upload concurrently through the existing
backend upload limit. A submission guard prevents duplicate Generate clicks.

Image rendering now decodes each still once instead of looping it as a video
input. The original image dimensions, placement, text filters and JPEG output
are retained. Windows admission locks use short nonblocking retries rather than
msvcrt's one-second retry intervals.

The runtime Python environment was missing psutil; it has now been installed.
Before that, memory admission could fail before claiming a job, leaving a QUEUED
record with no live worker. Local eager task execution now handles Retry with a
delay rather than recursively applying it immediately, and marks startup failures
FAILED so clients receive an error instead of polling forever.

## Local measurement

`python scripts/benchmark_image.py` renders five isolated 1280x720 JPEG images
containing an uploaded-style PNG logo plus text and verifies image dimensions
and visible text. [Raw report](benchmark-image-local.json):

* Average render time: 0.0686 seconds.
* Maximum render time: 0.0893 seconds.
* Five completed outputs.

This measures rendering only, not the complete HTTP flow, upload time, a busy
queue, MongoDB latency, remote fonts/assets or download time. It does not guarantee
all real templates complete end-to-end within two seconds. Capacity and memory
protection remain enabled. A job waiting behind other renders can take longer.

Restart the backend after dependency/code updates, reload the frontend and submit
a new image request. Previously stranded development jobs may remain queued;
the in-memory queue does not restore old submissions across restarts. Production
uses the existing persistent Celery recovery path.

Regression checks: backend waiting-status/auth/local-retry tests, real image/video
pipeline tests, `node scripts/test-render-jobs.cjs` and existing auth-session tests.
