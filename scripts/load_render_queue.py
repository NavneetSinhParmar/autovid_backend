"""Opt-in staging API burst and completion measurement. Never purges jobs."""
import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from resource_metrics import Sampler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--template-id", required=True)
    parser.add_argument("--counts", default="10,30,70,100")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--execute", action="store_true", help="Explicit opt-in: creates real render jobs")
    parser.add_argument("--output", default="load-render-results.json")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Requires --execute; use a staging deployment")
    token = os.environ.get("ACCESS_TOKEN")
    if not token:
        parser.error("Set ACCESS_TOKEN in the environment")
    headers = {"Authorization": f"Bearer {token}"}
    base = args.base_url.rstrip("/")
    reports = []
    for count in map(int, args.counts.split(",")):
        if not 1 <= count <= 500:
            parser.error("Submission counts must be between 1 and 500")
        def submit(_):
            start = time.perf_counter()
            try:
                response = requests.post(f"{base}/templates/{args.template_id}/preview", headers=headers, timeout=30)
                data = response.json()
                return {"http_status": response.status_code, "response_seconds": time.perf_counter() - start, "job_id": data.get("job_id")}
            except requests.RequestException:
                return {"http_status": 0, "response_seconds": time.perf_counter() - start, "job_id": None}
        with Sampler() as sampler:
            with ThreadPoolExecutor(max_workers=count) as pool:
                submissions = list(pool.map(submit, range(count)))
            pending = {item["job_id"] for item in submissions if item["job_id"]}
            results = []
            deadline = time.monotonic() + args.timeout
            while pending and time.monotonic() < deadline:
                for job_id in list(pending):
                    try:
                        response = requests.get(f"{base}/render-jobs/{job_id}", headers=headers, timeout=10)
                        if response.status_code != 200:
                            continue
                        job = response.json()
                        if job.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
                            results.append(job)
                            pending.remove(job_id)
                    except requests.RequestException:
                        pass
                time.sleep(1)
        durations = [float(j["render_duration"]) for j in results if j.get("render_duration") is not None]
        waits = [(datetime.fromisoformat(j["started_at"]) - datetime.fromisoformat(j["created_at"])).total_seconds()
                 for j in results if j.get("started_at") and j.get("created_at")]
        reports.append({"submissions": count, "accepted": sum(bool(s["job_id"]) for s in submissions),
                        "completed": sum(j["status"] == "COMPLETED" for j in results),
                        "failed": sum(j["status"] == "FAILED" for j in results), "unfinished": len(pending),
                        "average_render_seconds": statistics.mean(durations) if durations else None,
                        "maximum_render_seconds": max(durations) if durations else None,
                        "average_queue_wait_seconds": statistics.mean(waits) if waits else None,
                        "average_api_response_seconds": statistics.mean(s["response_seconds"] for s in submissions),
                        "maximum_api_response_seconds": max(s["response_seconds"] for s in submissions),
                        "resources": sampler.summary(), "submission_results": submissions})
        Path(args.output).write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in reports[-1].items() if k != "submission_results"}))


if __name__ == "__main__":
    main()
