"""Synthetic 720p overlay/text/audio benchmark; opt-in and stage-gated."""
import argparse
import json
import math
import os
import platform
import statistics
import struct
import subprocess
import sys
import time
import uuid
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def child(root, index, seconds):
    from app.services.video_renderer import render_preview
    from app.services.render_queue import current_render_temp_dir
    from app.services.render_resources import CapacityUnavailable
    from app.services.output_validator import validate_generated_video
    folder = root / f"job_{index}"
    folder.mkdir()
    token = current_render_temp_dir.set(str(folder))
    template = {"duration": seconds, "template_json": {"design": {
        "size": {"width": 1280, "height": 720}, "fps": 30,
        "trackItemIds": ["background", "logo", "text", "audio"],
        "tracks": [{"type": "text", "items": ["text"]}],
        "trackItemsMap": {
            "background": {"type": "image", "details": {"src": str(root / "background.png"), "width": 1280, "height": 720}},
            "logo": {"type": "image", "details": {"src": str(root / "logo.png"), "width": 180, "height": 180, "left": 100, "top": 150}},
            "text": {"type": "text", "details": {"text": "AutoVid 720p render benchmark", "fontSize": 42, "color": "#ffffff", "left": 320, "top": 300, "width": 850}},
            "audio": {"type": "audio", "details": {"src": str(root / "audio.wav")}, "display": {"from": 0, "to": seconds * 1000}},
        },
    }}}
    # Fixtures live outside application media; don't apply API source URL rewriting.
    import app.services.video_renderer as renderer
    renderer.normalize_media_src = lambda value: value
    original_popen = subprocess.Popen
    class ObservedPopen(original_popen):
        def __init__(self, command, **kwargs):
            super().__init__(command, **kwargs)
            self.marker = None
            if Path(command[0]).name.lower() in {"ffmpeg", "ffmpeg.exe"}:
                self.marker = root / f"ffmpeg_{index}.pid"
                self.marker.write_text(str(self.pid))
                with open(root / f"events_{index}.jsonl", "a") as handle:
                    handle.write(json.dumps({"time": time.time(), "delta": 1}) + "\n")
        def __exit__(self, *args):
            try:
                return super().__exit__(*args)
            finally:
                if self.marker:
                    self.marker.unlink(missing_ok=True)
                    with open(root / f"events_{index}.jsonl", "a") as handle:
                        handle.write(json.dumps({"time": time.time(), "delta": -1}) + "\n")
    subprocess.Popen = ObservedPopen
    (root / f"ready_{index}").touch()
    while not (root / "go").exists():
        time.sleep(0.05)
    requested = time.perf_counter()
    start = requested
    try:
        while True:
            start = time.perf_counter()
            try:
                render_preview(template, {}, str(folder / "output.mp4"))
                break
            except CapacityUnavailable:
                if time.perf_counter() - requested > 60:
                    raise
                time.sleep(0.2)
        result = {"completed": True, "render_seconds": time.perf_counter() - start,
                  "queue_wait_seconds": start - requested,
                  "output": validate_generated_video(str(folder / "output.mp4"))}
    except Exception as exc:
        result = {"completed": False, "error_type": type(exc).__name__, "error": str(exc)}
    finally:
        current_render_temp_dir.reset(token)
    (root / f"result_{index}.json").write_text(json.dumps(result), encoding="utf-8")
    return 0 if result["completed"] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", default="2,4,6,8,10")
    parser.add_argument("--validated-max", type=int, default=2, help="Highest stage authorized after reviewing prior resource results")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", default="benchmark-concurrency-results.json")
    parser.add_argument("--child-root")
    parser.add_argument("--child-index", type=int)
    args = parser.parse_args()
    if args.child_root:
        return child(Path(args.child_root), args.child_index, args.seconds)
    if not args.execute:
        parser.error("Requires --execute; run on an isolated staging host")
    if not 0 < args.seconds <= 900 or not 1 <= args.validated_max <= 10:
        parser.error("Invalid duration or stage limit")
    import psutil
    from PIL import Image
    from resource_metrics import Sampler
    base = Path("media/concurrency_benchmarks") / uuid.uuid4().hex
    base.mkdir(parents=True)
    reports = []
    for count in map(int, args.counts.split(",")):
        if not 1 <= count <= 10:
            parser.error("Counts must be 1 through 10")
        if count > args.validated_max:
            reports.append({"target": count, "skipped": "Review lower-stage results and increase --validated-max explicitly"})
            continue
        required_mb = int(os.getenv("RENDER_MIN_FREE_MEMORY_MB", "1024")) + count * int(os.getenv("RENDER_MEMORY_PER_PROCESS_MB", "512"))
        if psutil.virtual_memory().available / 2**20 < required_mb:
            reports.append({"target": count, "skipped": "Insufficient measured available memory"})
            continue
        root = (base / str(count)).resolve()
        root.mkdir()
        Image.new("RGB", (1280, 720), "#203040").save(root / "background.png")
        Image.new("RGBA", (180, 180), "#ef6020").save(root / "logo.png")
        with wave.open(str(root / "audio.wav"), "wb") as handle:
            handle.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            handle.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 24000))) for i in range(int(24000 * args.seconds))))
        env = dict(os.environ)
        env.update(MAX_CONCURRENT_VIDEO_RENDERS=str(count), CELERY_RENDER_CONCURRENCY=str(count),
                   RENDER_LOCK_DIR=str(root / "locks"), FFMPEG_THREADS="1", FFMPEG_FILTER_THREADS="1")
        children = []
        with Sampler(root) as sampler:
            try:
                for index in range(count):
                    children.append(subprocess.Popen([sys.executable, __file__, "--child-root", str(root), "--child-index", str(index), "--seconds", str(args.seconds)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                deadline = time.monotonic() + 90
                while len(list(root.glob("ready_*"))) < count and time.monotonic() < deadline and all(p.poll() is None for p in children):
                    time.sleep(0.1)
                (root / "go").touch()
                start = time.perf_counter()
                for process in children:
                    process.wait(timeout=700)
                wall = time.perf_counter() - start
            finally:
                for process in children:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        results = [json.loads(p.read_text()) for p in root.glob("result_*.json")]
        durations = [r["render_seconds"] for r in results if r.get("completed")]
        events = sorted([json.loads(line) for file in root.glob("events_*.jsonl") for line in file.read_text().splitlines()], key=lambda event: event["time"])
        active = peak = 0
        for event in events:
            active += event["delta"]
            peak = max(peak, active)
        reports.append({"target": count, "completed": len(durations), "failed": count - len(durations),
                        "average_render_seconds": statistics.mean(durations) if durations else None,
                        "maximum_render_seconds": max(durations) if durations else None,
                        "average_queue_wait_seconds": statistics.mean(r["queue_wait_seconds"] for r in results if r.get("completed")) if durations else None,
                        "wall_seconds": wall, "actual_peak_ffmpeg_processes": peak,
                        "resources": sampler.summary(), "results": results, "artifact_root": str(root)})
    report = {"platform": platform.platform(), "cpu_logical": psutil.cpu_count(), "ram_mb": psutil.virtual_memory().total / 2**20,
              "template": "synthetic 720p PNG overlays, text and sine-wave audio", "seconds": args.seconds, "stages": reports}
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(any(stage.get("failed", 0) for stage in reports))


if __name__ == "__main__":
    raise SystemExit(main())
