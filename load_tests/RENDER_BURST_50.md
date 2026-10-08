# 50 simultaneous render API calls

Run the backend and workers first. Both template IDs must be **public and active**:
one video template and one image template. This test creates real render jobs and
outputs; use local/staging data. It needs only Python's standard library.

From PowerShell:

```powershell
Set-Location C:\project\video-img-genrated\backend
python scripts/test_render_burst.py --video-template YOUR_VIDEO_TEMPLATE_ID --image-template YOUR_IMAGE_TEMPLATE_ID --wait
```

Default: **50 total calls released together: 25 video + 25 image**. A thread
barrier starts the requests together; network/server scheduling can still differ.
Submission success is HTTP 202 with a job ID. The `--wait` option polls each job
and reports completion, failures and observed elapsed time. It does not download
50 output files, so download transfer time is not included. Worker duration and
queue/polling-inclusive observed completion are separate fields in the report.

If you want **50 video + 50 image = 100 total calls**:

```powershell
python scripts/test_render_burst.py --video-template YOUR_VIDEO_TEMPLATE_ID --image-template YOUR_IMAGE_TEMPLATE_ID --video-count 50 --image-count 50 --wait --report render_burst_100.json
```

Other server:

```powershell
python scripts/test_render_burst.py --base-url http://localhost:8000 --video-template YOUR_VIDEO_TEMPLATE_ID --image-template YOUR_IMAGE_TEMPLATE_ID --wait --wait-seconds 1800
```

To submit only, omit `--wait`. Default client wait is 900 seconds, request timeout
30 seconds, and polling interval 2.5 seconds. Expiring the client wait does not
cancel server jobs. A nonzero script exit code means a submission failed or, with
`--wait`, not every job completed successfully within the observation window.

Results: `backend/render_burst_report.json`, including request latency, job ID,
type, terminal status, worker duration and observed completion time. Public job
access tokens are used in memory for polling and are not written to the report.

Personalized input: create a JSON file containing the same request body your UI
sends, then add `--payload-file payload.json`. The same body is sent to both
templates; use field names valid for them. Default body is `{"fields": {}}` and
uses template defaults.

Interpretation:

- HTTP 404: template is unavailable, not public/active, or the ID is wrong.
- HTTP 429: render submission rate limit reached; wait for the window to reset.
- HTTP 202: accepted/queued, not proof that rendering has completed.
- FAILED: inspect that job's error in the report.
- QUEUED/PROCESSING at client deadline: rendering is still pending/running.

Current configuration permits 100 active video jobs per process; image capacity
is 4 per process, so image jobs can queue. All worker types share machine resources.
This script measures the actual batch rather than assuming previous two-job
benchmarks predict performance at 50/100 concurrent submissions.
