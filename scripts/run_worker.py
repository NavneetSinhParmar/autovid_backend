"""Systemd/Procfile entry point: read the same settings as the application."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # Loads environment before reading settings.
from app.core.settings import settings


if __name__ == "__main__":
    queue = sys.argv[1] if len(sys.argv) > 1 else "render_video"
    limits = {"render_video": settings.video_worker_concurrency,
              "render_image": settings.image_worker_concurrency,
              "tts": settings.tts_worker_concurrency, "campaigns,maintenance": 1}
    if queue == "beat":
        args = ["beat", "--loglevel=info", "--schedule=" + os.getenv("CELERY_BEAT_SCHEDULE", "./celerybeat-schedule")]
    elif queue in limits:
        args = ["worker", "--pool=prefork", "-Q", queue,
                f"--concurrency={limits[queue]}", "--loglevel=info",
                "--hostname=" + queue.replace(",", "-") + "@%h"]
    else:
        raise SystemExit("Unsupported queue")
    os.execv(sys.executable, [sys.executable, "-m", "celery", "-A", "app.worker.video_worker.celery_app", *args])
