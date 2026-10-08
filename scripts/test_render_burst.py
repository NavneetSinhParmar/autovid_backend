"""Simultaneous public image/video API submissions, optionally waiting for jobs."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request_json(url, payload=None, timeout=30):
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        return error.code, {"error": detail[:1500]}
    except (URLError, OSError, ValueError) as error:
        return 0, {"error": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--video-template", required=True)
    parser.add_argument("--image-template", required=True)
    parser.add_argument("--video-count", type=int, default=25)
    parser.add_argument("--image-count", type=int, default=25)
    parser.add_argument("--payload-file", help='Optional JSON body, e.g. {"fields": {}}')
    parser.add_argument("--wait", action="store_true", help="Poll submitted jobs to terminal status")
    parser.add_argument("--wait-seconds", type=float, default=900)
    parser.add_argument("--poll-seconds", type=float, default=2.5)
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--report", default="render_burst_report.json")
    args = parser.parse_args()
    total = args.video_count + args.image_count
    if min(args.video_count, args.image_count) < 0 or total < 1 or total > 500:
        parser.error("Counts must be non-negative and total must be between 1 and 500")
    if min(args.wait_seconds, args.poll_seconds, args.request_timeout) <= 0:
        parser.error("Timeouts and polling interval must be positive")
    payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8")) if args.payload_file else {"fields": {}}
    if not isinstance(payload, dict):
        parser.error("Payload must be a JSON object")
    base = args.base_url.rstrip("/")
    barrier = threading.Barrier(total)
    start = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()

    def submit(index, kind, template):
        barrier.wait()
        sent_at = time.perf_counter()
        code, data = request_json(f"{base}/public/templates/{template}/preview", payload, args.request_timeout)
        result = {
            "index": index, "type": kind, "template_id": template,
            "http_status": code, "accepted": code == 202 and bool(data.get("job_id")),
            "request_seconds": round(time.perf_counter() - sent_at, 3),
            "submitted_after_seconds": round(sent_at - start, 3),
            "job_id": data.get("job_id"),
        }
        if not result["accepted"]:
            result["error"] = data.get("error", data)
        # Keep capabilities in memory only; do not print or write them to the report.
        return result, data.get("access_token")

    work = [("video", args.video_template)] * args.video_count + [("image", args.image_template)] * args.image_count
    print(f"Submitting {total} simultaneous requests: {args.video_count} video + {args.image_count} image")
    with ThreadPoolExecutor(max_workers=total) as pool:
        futures = [pool.submit(submit, i + 1, kind, template) for i, (kind, template) in enumerate(work)]
        submitted = [future.result() for future in futures]
    accepted = sum(result["accepted"] for result, _ in submitted)
    submission_seconds = round(time.perf_counter() - start, 3)
    print(f"Accepted: {accepted}/{total}; submission batch: {submission_seconds}s")
    for result, _ in submitted:
        if not result["accepted"]:
            print(f"Request {result['index']} ({result['type']}): HTTP {result['http_status']} {result['error']}")

    pending = [(result, token) for result, token in submitted if result["accepted"]]
    if args.wait and pending:
        deadline = time.perf_counter() + args.wait_seconds

        def poll(entry):
            result, token = entry
            query = "?" + urlencode({"access_token": token}) if token else ""
            code, data = request_json(f"{base}/render-jobs/{result['job_id']}{query}", timeout=args.request_timeout)
            if code == 200:
                result["status"] = data.get("status")
                result["worker_render_seconds"] = data.get("render_duration")
                if result["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                    result["observed_completion_seconds"] = round(time.perf_counter() - start, 3)
                    if result["status"] != "COMPLETED":
                        result["error"] = data.get("error") or data.get("error_message")
                    return None
            else:
                result["last_poll_http_status"] = code
            return entry

        with ThreadPoolExecutor(max_workers=min(total, 50)) as pool:
            while pending and time.perf_counter() < deadline:
                pending = [entry for entry in pool.map(poll, pending) if entry is not None]
                completed = sum(result.get("status") == "COMPLETED" for result, _ in submitted)
                print(f"Completed: {completed}/{accepted}; pending: {len(pending)}; elapsed: {time.perf_counter() - start:.1f}s", flush=True)
                if pending:
                    time.sleep(min(args.poll_seconds, max(0, deadline - time.perf_counter())))
        for result, _ in pending:
            result["client_wait_expired"] = True
        if pending:
            print("Client stopped waiting; server jobs continue running.")

    report = {
        "started_at": started_at, "base_url": base, "total": total,
        "video_count": args.video_count, "image_count": args.image_count,
        "accepted": accepted, "submission_seconds": submission_seconds,
        "elapsed_seconds": round(time.perf_counter() - start, 3),
        "completed": sum(result.get("status") == "COMPLETED" for result, _ in submitted),
        "jobs": [result for result, _ in submitted],
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {Path(args.report).resolve()}")
    success = accepted == total and (not args.wait or report["completed"] == total)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
