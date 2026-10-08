import os

from celery import Celery


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


VIDEO_WORKER_CONCURRENCY = _env_int("VIDEO_WORKER_CONCURRENCY", 100)

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
    worker_concurrency=VIDEO_WORKER_CONCURRENCY,
    task_default_queue="render_video",
    task_routes={
        "app.worker.video_worker.render_video_task": {"queue": "render_video"},
        "app.worker.video_worker.render_image_task": {"queue": "render_image"},
        "app.worker.video_worker.generate_tts_task": {"queue": "tts"},
        "app.worker.video_worker.prepare_render_tts_task": {"queue": "tts"},
        "app.worker.video_worker.expand_campaign_task": {"queue": "campaigns"},
        "app.worker.video_worker.recover_stuck_jobs": {"queue": "maintenance"},
    },
    beat_schedule={
        "recover-stuck-render-jobs": {
            "task": "app.worker.video_worker.recover_stuck_jobs",
            "schedule": 60.0,
        },
    },
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": _env_int("CELERY_VISIBILITY_TIMEOUT_SECONDS", 86400)},
    result_backend_transport_options={"visibility_timeout": _env_int("CELERY_VISIBILITY_TIMEOUT_SECONDS", 86400)},
    visibility_timeout=_env_int("CELERY_VISIBILITY_TIMEOUT_SECONDS", 86400),
)
