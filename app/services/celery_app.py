import os

from celery import Celery


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


FFMPEG_WORKER_CONCURRENCY = _env_int("FFMPEG_WORKER_CONCURRENCY", 2)

celery_app = Celery(
    "autovid_render_worker",
    broker=REDIS_URL,
    backend=os.getenv("CELERY_RESULT_BACKEND", REDIS_URL),
    include=["app.worker.video_worker"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    worker_concurrency=FFMPEG_WORKER_CONCURRENCY,
    task_default_queue="render",
    broker_connection_retry_on_startup=True,
)
