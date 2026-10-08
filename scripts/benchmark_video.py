"""Benchmark a saved template without modifying it or adding application logs."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from bson import ObjectId
from app.services.sync_db import sync_db
from app.services import video_renderer as renderer
from app.services.output_validator import validate_generated_video
from app.services.render_queue import current_render_temp_dir

parser = argparse.ArgumentParser()
parser.add_argument("--template-id", required=True)
parser.add_argument("--label", default="benchmark")
parser.add_argument("--preset")
parser.add_argument("--threads", type=int)
parser.add_argument("--crf", type=int)
parser.add_argument("--latest-job", action="store_true", help="Use the actual personalized payload of the latest job")
args = parser.parse_args()
if args.preset:
    import os
    os.environ["FFMPEG_PRESET"] = args.preset
if args.crf is not None:
    import os
    os.environ["FFMPEG_CRF"] = str(args.crf)
if args.threads:
    renderer.FFMPEG_THREADS = args.threads
template = deepcopy(sync_db.templates.find_one({"_id": ObjectId(args.template_id)}))
context = {"customer": {}, "company": {}}
if args.latest_job:
    job = sync_db.render_jobs.find_one({"template_id": args.template_id}, sort=[("created_at", -1)])
    if not job or not job.get("payload"):
        raise SystemExit("No saved render payload found for this template")
    template = deepcopy(job["payload"]["template"])
    context = deepcopy(job["payload"].get("context") or context)
if not template:
    raise SystemExit("Template not found")
folder = Path("media/render_performance")
folder.mkdir(parents=True, exist_ok=True)
token = current_render_temp_dir.set(str(folder.resolve()))
measurements = {"font_resolution_seconds": 0, "ffprobe_seconds": 0, "ffmpeg_seconds": 0}
for name, metric in [("resolve_font_file", "font_resolution_seconds"), ("_run_with_resolved_exec", None)]:
    original = getattr(renderer, name)
    def timed(*values, _original=original, _metric=metric, **kwargs):
        metric = _metric or ("ffprobe_seconds" if kwargs.get("exec_name") == "ffprobe" else "ffmpeg_seconds")
        start = time.perf_counter()
        try:
            return _original(*values, **kwargs)
        finally:
            measurements[metric] += time.perf_counter() - start
    setattr(renderer, name, timed)
output = folder / f"{args.label}.mp4"
start = time.perf_counter()
measurements["started_at"] = datetime.now(timezone.utc).isoformat()
renderer.render_preview(template, context, str(output))
measurements["render_seconds"] = time.perf_counter() - start
measurements["finished_at"] = datetime.now(timezone.utc).isoformat()
start = time.perf_counter()
measurements["output"] = validate_generated_video(str(output))
measurements["output_validation_seconds"] = time.perf_counter() - start
measurements["output_bytes"] = output.stat().st_size
measurements["template_id"] = args.template_id
measurements["label"] = args.label
measurements["fps"] = renderer.resolve_fps(template["template_json"]["design"])
(folder / f"{args.label}.json").write_text(json.dumps(measurements, indent=2))
print(json.dumps(measurements, indent=2))
current_render_temp_dir.reset(token)
