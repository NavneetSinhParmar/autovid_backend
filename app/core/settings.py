import os
from dataclasses import dataclass


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, default).split(",") if value.strip())


@dataclass(frozen=True)
class Settings:
    cors_origins: tuple[str, ...] = _csv("CORS_ORIGINS", "http://localhost:3000")
    max_image_bytes: int = _int("MAX_IMAGE_UPLOAD_MB", 60) * 1024 * 1024
    max_video_bytes: int = _int("MAX_VIDEO_UPLOAD_MB", 60) * 1024 * 1024
    max_audio_bytes: int = _int("MAX_AUDIO_UPLOAD_MB", 60) * 1024 * 1024
    max_image_width: int = _int("MAX_IMAGE_WIDTH", 8192)
    max_image_height: int = _int("MAX_IMAGE_HEIGHT", 8192)
    max_audio_seconds: float = _float("MAX_AUDIO_SECONDS", 600.0)
    ffmpeg_threads: int = _int("FFMPEG_THREADS", 1)
    ffmpeg_filter_threads: int = _int("FFMPEG_FILTER_THREADS", 1)
    ffmpeg_timeout_seconds: int = _int("FFMPEG_TIMEOUT_SECONDS", 600)
    max_render_retries: int = _int("MAX_RENDER_RETRIES", 2, minimum=0)
    video_worker_concurrency: int = min(10, _int("CELERY_RENDER_CONCURRENCY", _int("VIDEO_WORKER_CONCURRENCY", 2)))
    max_concurrent_video_renders: int = min(10, _int("MAX_CONCURRENT_VIDEO_RENDERS", 2))
    min_free_memory_mb: int = _int("RENDER_MIN_FREE_MEMORY_MB", 1024, minimum=0)
    estimated_render_memory_mb: int = _int("RENDER_MEMORY_PER_PROCESS_MB", 512)
    max_source_video_seconds: float = _float("MAX_SOURCE_VIDEO_SECONDS", 1800)
    max_output_video_seconds: float = _float("MAX_OUTPUT_VIDEO_SECONDS", 900)
    max_output_width: int = min(1280, _int("MAX_OUTPUT_WIDTH", 1280, minimum=2))
    max_output_height: int = min(720, _int("MAX_OUTPUT_HEIGHT", 720, minimum=2))
    max_pending_render_jobs: int = _int("MAX_PENDING_RENDER_JOBS", 500)
    worker_max_memory_kb: int = _int("CELERY_WORKER_MAX_MEMORY_PER_CHILD_KB", 768000)
    image_worker_concurrency: int = _int("IMAGE_WORKER_CONCURRENCY", 4)
    tts_worker_concurrency: int = _int("TTS_WORKER_CONCURRENCY", 2)
    upload_processing_concurrency: int = _int("UPLOAD_PROCESSING_CONCURRENCY", 4)
    request_rate_limit: int = _int("REQUEST_RATE_LIMIT_PER_MINUTE", 120)
    upload_rate_limit: int = _int("UPLOAD_RATE_LIMIT_PER_MINUTE", 120)
    render_rate_limit: int = _int("RENDER_RATE_LIMIT_PER_MINUTE", 120)
    tts_rate_limit: int = _int("TTS_RATE_LIMIT_PER_MINUTE", 10)
    stale_job_seconds: int = _int("STALE_JOB_SECONDS", 900)
    request_timeout_seconds: int = _int("REQUEST_TIMEOUT_SECONDS", 30)
    render_retention_days: int = _int("RENDER_RETENTION_DAYS", 30)


settings = Settings()
