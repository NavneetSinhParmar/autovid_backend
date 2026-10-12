import asyncio
import contextvars
import logging
import os
import shutil
import uuid
import hashlib
import secrets
import weakref
from time import sleep as _retry_sleep
from time import monotonic as _retry_clock
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Any

from app.core.errors import AppError
from app.services.storage import ensure_media_folder, get_media_abs_path
from app.services.url import build_media_url
from app.core.settings import settings
from app.services.render_resources import FileLock

logger = logging.getLogger(__name__)
_admission_locks = weakref.WeakKeyDictionary()

RENDER_JOB_ROOT = os.getenv("RENDER_JOB_ROOT", "render_jobs")
RENDER_QUEUE_BACKEND = os.getenv(
    "RENDER_QUEUE_BACKEND", "memory" if os.getenv("APP_ENV") == "development" else "celery"
).lower()
_local_executors = {
    "render_video": ThreadPoolExecutor(max_workers=settings.video_worker_concurrency, thread_name_prefix="video"),
    "render_image": ThreadPoolExecutor(max_workers=settings.image_worker_concurrency, thread_name_prefix="image"),
    "tts": ThreadPoolExecutor(max_workers=settings.tts_worker_concurrency, thread_name_prefix="tts"),
}


def dispatch_render_task(task_name: str, job_id: str, queue: str) -> None:
    if RENDER_QUEUE_BACKEND == "memory":
        enforce_single_worker_for_memory_queue()
        _local_executors[queue].submit(_execute_local_task, task_name, job_id)
    elif RENDER_QUEUE_BACKEND == "celery":
        from app.services.celery_app import celery_app
        celery_app.send_task(task_name, args=[job_id], queue=queue)
    else:
        raise ValueError("RENDER_QUEUE_BACKEND must be memory or celery")


def resume_local_pending_jobs() -> int:
    """Restore durable queued jobs after a development server reload."""
    if RENDER_QUEUE_BACKEND != "memory":
        return 0
    from app.services.sync_db import sync_db
    from app.worker.video_worker import _job_route
    resumed = 0
    for job in sync_db.render_jobs.find({"status": "QUEUED"}).sort("created_at", 1):
        lock = FileLock("job_" + job["job_id"])
        if not lock.acquire():
            continue
        try:
            task_name, queue = _job_route(job)
            dispatch_render_task(task_name, job["job_id"], queue)
            resumed += 1
        finally:
            lock.close()
    logger.info("[LOCAL RENDER] Restored %s queued jobs after startup", resumed)
    return resumed


def _execute_local_task(task_name: str, job_id: str) -> None:
    from celery.exceptions import Retry
    from app.services.render_resources import CapacityUnavailable
    retries = 0
    capacity_deadline = _retry_clock() + settings.ffmpeg_timeout_seconds
    try:
        from app.worker import video_worker  # Registers the shared worker tasks.
        from app.services.celery_app import celery_app
        while True:
            try:
                # Eager apply otherwise recursively executes retries without
                # respecting countdown, unlike a real Celery worker.
                celery_app.tasks[task_name].apply(args=[job_id], throw=True, retries=retries)
                return
            except Retry as exc:
                if isinstance(exc.exc, CapacityUnavailable) and _retry_clock() >= capacity_deadline:
                    from app.services.sync_db import sync_db
                    sync_db.render_jobs.update_one(
                        {"job_id": job_id, "status": "QUEUED"},
                        {"$set": {"status": "FAILED", "error_code": "RENDER_CAPACITY_TIMEOUT",
                                  "error": str(exc.exc), "failed_at": _now(), "updated_at": _now()}},
                    )
                    logger.error("[LOCAL RENDER] Capacity wait timed out job_id=%s", job_id)
                    return
                delay = 1 if isinstance(exc.exc, CapacityUnavailable) else float(exc.when or 1)
                _retry_sleep(delay)
                retries += 1
    except Exception as exc:
        logger.error("[LOCAL RENDER] FAILED job_id=%s error_type=%s", job_id, type(exc).__name__)
        from app.services.sync_db import sync_db
        sync_db.render_jobs.update_one(
            {"job_id": job_id, "status": "QUEUED"},
            {"$set": {"status": "FAILED", "error_code": "LOCAL_WORKER_ERROR",
                      "error": "Local rendering worker could not start; check backend dependencies and logs",
                      "error_details": {"type": type(exc).__name__}, "failed_at": _now(), "updated_at": _now()}},
        )

current_render_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_render_job_id",
    default=None,
)
current_render_temp_dir: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_render_temp_dir",
    default=None,
)


@dataclass
class RenderJob:
    job_id: str
    sequence: int
    kind: str
    extension: str
    work: Callable[[str, str, str], Awaitable[Any]]
    done: asyncio.Future


_queue: asyncio.Queue[RenderJob] = asyncio.Queue()
_jobs: dict[str, dict] = {}
_worker_task: asyncio.Task | None = None
_sequence = 0


def _now() -> datetime:
    return datetime.utcnow()


def normalize_render_status(status: str | None) -> str:
    return (status or "QUEUED").upper()


async def enqueue_celery_render_job(
    **kwargs,
) -> dict:
    # Avoid a thundering herd of OS-lock attempts within one API event loop.
    loop = asyncio.get_running_loop()
    local_lock = _admission_locks.setdefault(loop, asyncio.Lock())
    async with local_lock:
        return await _admit_render_job(kwargs)


async def _admit_render_job(kwargs):
    # Cross-process admission, shared with campaign expansion.
    lock = FileLock("queue_admission")
    while not lock.acquire():
        await asyncio.sleep(0.01)
    try:
        return await _enqueue_celery_render_job(**kwargs)
    finally:
        lock.close()


async def _enqueue_celery_render_job(
    *,
    kind: str,
    extension: str,
    video_task_id: str | None = None,
    payload: dict | None = None,
    company_id: str,
    campaign_id: str | None = None,
    customer_id: str | None = None,
    template_id: str | None = None,
    idempotency_key: str | None = None,
    public_access: bool = False,
    priority: int = 0,
) -> dict:
    from bson import ObjectId

    from app.db.connection import db
    payload = dict(payload or {})
    if payload.get("dynamic_tts"):
        track_map = (((payload.get("template") or {}).get("template_json") or {}).get("design") or {}).get("trackItemsMap") or {}
        payload["dynamic_tts"] = any(
            item.get("type") == "audio"
            and (item.get("metadata") or {}).get("isCustomerField")
            and str((item.get("metadata") or {}).get("fieldPath") or "").lower() == "voiceover"
            and str(item.get("voisetext") or (item.get("details") or {}).get("voisetext") or "").strip()
            for item in track_map.values()
        )
    if idempotency_key:
        existing = await db.render_jobs.find_one({"company_id": company_id, "idempotency_key": idempotency_key})
        if existing:
            existing["id"] = str(existing.pop("_id"))
            existing.pop("payload", None)
            existing.pop("access_token_hash", None)
            return existing

    pending = await db.render_jobs.count_documents({"status": {"$in": ["QUEUED", "PROCESSING"]}})
    if pending >= settings.max_pending_render_jobs:
        raise AppError(429, "RENDER_QUEUE_FULL", "Render queue admission limit reached; retry later")

    job_id = uuid.uuid4().hex
    extension = extension.lstrip(".")
    folder = f"{RENDER_JOB_ROOT}/{job_id}"
    tmp_folder = f"{folder}/temp"
    output_folder = f"{folder}/output"
    ensure_media_folder(tmp_folder)
    ensure_media_folder(output_folder)

    now = _now()
    output_relative = f"{output_folder}/output.{extension}"
    access_token = secrets.token_urlsafe(32) if public_access else None
    status = {
        "job_id": job_id,
        "kind": kind,
        "job_type": kind,
        "company_id": company_id,
        "user_id": ((payload.get("context") or {}).get("company") or {}).get("user_id"),
        "campaign_id": campaign_id,
        "customer_id": customer_id,
        "template_id": template_id,
        "status": "QUEUED",
        "progress": 0,
        "priority": max(-10, min(10, int(priority))),
        "retry_count": 0,
        "video_task_id": video_task_id,
        "folder": folder,
        "tmp_folder": tmp_folder,
        "output_relative_path": output_relative,
        "output_url": None,
        "error": None,
        "error_code": None,
        "error_details": None,
        "created_at": now,
        "queued_at": now,
        "started_at": None,
        "completed_at": None,
        "failed_at": None,
        "updated_at": now,
        "render_duration": None,
        "idempotency_key": idempotency_key,
        "access_token_hash": hashlib.sha256(access_token.encode()).hexdigest() if access_token else None,
        "status_url": f"/render-jobs/{job_id}",
        "download_url": f"/render-jobs/{job_id}/download",
        "payload": payload or {},
    }
    try:
        await db.render_jobs.insert_one(status.copy())
    except Exception as exc:
        from pymongo.errors import DuplicateKeyError
        if not isinstance(exc, DuplicateKeyError) or not idempotency_key:
            raise
        existing = await db.render_jobs.find_one({"company_id": company_id, "idempotency_key": idempotency_key}, {"payload": 0, "access_token_hash": 0})
        if not existing:
            raise
        existing["id"] = str(existing.pop("_id"))
        return existing

    if video_task_id:
        await db.video_tasks.update_one(
            {"_id": ObjectId(video_task_id)},
            {"$set": {
                "render_job_id": job_id,
                "status": "QUEUED",
                "progress": 0,
                "output_url": None,
                "error": None,
                "error_details": None,
                "updated_at": now,
            }},
        )

    try:
        if kind == "tts":
            task_name, queue = "app.worker.video_worker.generate_tts_task", "tts"
        elif (payload or {}).get("dynamic_tts"):
            task_name, queue = "app.worker.video_worker.prepare_render_tts_task", "tts"
        elif extension in {"jpg", "jpeg", "png", "webp"}:
            task_name, queue = "app.worker.video_worker.render_image_task", "render_image"
        else:
            task_name, queue = "app.worker.video_worker.render_video_task", "render_video"
        await asyncio.to_thread(dispatch_render_task, task_name, job_id, queue)
    except Exception as exc:
        failed_at = _now()
        error = f"Failed to enqueue render job: {exc}"
        await db.render_jobs.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "QUEUED",
                "error": error,
                "error_code": "QUEUE_UNAVAILABLE",
                "error_details": {"type": exc.__class__.__name__, "message": str(exc)},
                "updated_at": failed_at,
            }},
        )
        if video_task_id:
            await db.video_tasks.update_one(
                {"_id": ObjectId(video_task_id)},
                {"$set": {
                    "status": "QUEUED",
                    "error": error,
                    "error_details": {"type": exc.__class__.__name__, "message": str(exc)},
                    "updated_at": failed_at,
                }},
            )
        raise AppError(
            503,
            "QUEUE_UNAVAILABLE",
            "Render queue is unavailable. Start Redis and the Celery worker, then retry.",
            {"job_id": job_id, "type": exc.__class__.__name__},
        ) from exc
    status.pop("payload", None)
    status.pop("access_token_hash", None)
    if access_token:
        status["access_token"] = access_token
    return status


def _configured_worker_count() -> int:
    raw = (
        os.getenv("WEB_CONCURRENCY")
        or os.getenv("UVICORN_WORKERS")
        or os.getenv("GUNICORN_WORKERS")
        or "1"
    )
    try:
        return int(raw)
    except ValueError:
        return 1


def enforce_single_worker_for_memory_queue() -> None:
    if RENDER_QUEUE_BACKEND == "memory" and _configured_worker_count() != 1:
        raise RuntimeError(
            "The in-memory render queue requires one app worker. "
            "Set WEB_CONCURRENCY=1 / --workers 1, or replace it with Redis/shared queue."
        )


def start_render_worker() -> None:
    global _worker_task
    enforce_single_worker_for_memory_queue()
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.get_running_loop().create_task(_render_worker())
    logger.info("[render_queue] FIFO render worker started concurrency=1")


def _ensure_worker_started() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    start_render_worker()


def get_render_job(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    return dict(job) if job else None


async def get_persisted_render_job(job_id: str) -> dict | None:
    from app.db.connection import db

    job = await db.render_jobs.find_one({"job_id": job_id}, {"payload": 0, "access_token_hash": 0})
    if not job:
        return get_render_job(job_id)
    job["id"] = str(job.pop("_id"))
    job["status"] = normalize_render_status(job.get("status"))
    return job


async def wait_for_render_job(job_id: str, timeout: float | None = None) -> dict | None:
    started = asyncio.get_running_loop().time()
    while True:
        job = get_render_job(job_id)
        if not job:
            return None
        if job["status"] in ("completed", "failed"):
            return job
        if timeout is not None and asyncio.get_running_loop().time() - started >= timeout:
            return job
        await asyncio.sleep(0.2)


def enqueue_render_job(
    *,
    kind: str,
    extension: str,
    work: Callable[[str, str, str], Awaitable[Any]],
) -> dict:
    global _sequence
    _ensure_worker_started()
    _sequence += 1
    job_id = uuid.uuid4().hex
    folder = f"{RENDER_JOB_ROOT}/{job_id}"
    ensure_media_folder(folder)
    loop = asyncio.get_running_loop()
    job = RenderJob(
        job_id=job_id,
        sequence=_sequence,
        kind=kind,
        extension=extension.lstrip("."),
        work=work,
        done=loop.create_future(),
    )
    status = {
        "job_id": job_id,
        "sequence": job.sequence,
        "kind": kind,
        "status": "queued",
        "status_url": f"/render-jobs/{job_id}",
        "download_url": f"/render-jobs/{job_id}/download",
        "output_url": None,
        "output_path": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _jobs[job_id] = status
    _queue.put_nowait(job)
    logger.info("[render_queue] job_id=%s sequence=%s queued kind=%s", job_id, job.sequence, kind)
    return dict(status)


async def run_render_job(
    *,
    kind: str,
    extension: str,
    work: Callable[[str, str, str], Awaitable[Any]],
) -> dict:
    job_info = enqueue_render_job(kind=kind, extension=extension, work=work)
    job_id = job_info["job_id"]
    job = await wait_for_render_job(job_id)
    if not job:
        raise RuntimeError("Render job disappeared")
    if job["status"] == "failed":
        raise RuntimeError(job.get("error") or "Render failed")
    return job


async def _render_worker() -> None:
    while True:
        job = await _queue.get()
        folder = f"{RENDER_JOB_ROOT}/{job.job_id}"
        tmp_folder = f"{folder}/tmp"
        ensure_media_folder(tmp_folder)
        output_relative = f"{folder}/output.{job.extension}"
        output_path = get_media_abs_path(output_relative)
        temp_path = get_media_abs_path(tmp_folder)
        token_job = current_render_job_id.set(job.job_id)
        token_tmp = current_render_temp_dir.set(temp_path)

        try:
            _jobs[job.job_id].update({
                "status": "processing",
                "started_at": _now(),
                "updated_at": _now(),
            })
            logger.info("[render_queue] job_id=%s sequence=%s processing", job.job_id, job.sequence)
            await job.work(job.job_id, output_path, folder)
            _jobs[job.job_id].update({
                "status": "completed",
                "output_url": build_media_url(output_relative),
                "output_path": output_path,
                "completed_at": _now(),
                "updated_at": _now(),
            })
            logger.info("[render_queue] job_id=%s sequence=%s completed", job.job_id, job.sequence)
            if not job.done.done():
                job.done.set_result(dict(_jobs[job.job_id]))
        except Exception as exc:
            _jobs[job.job_id].update({
                "status": "failed",
                "error": str(exc),
                "failed_at": _now(),
                "updated_at": _now(),
            })
            logger.exception("[render_queue] job_id=%s sequence=%s failed", job.job_id, job.sequence)
            if not job.done.done():
                job.done.set_exception(exc)
        finally:
            current_render_job_id.reset(token_job)
            current_render_temp_dir.reset(token_tmp)
            shutil.rmtree(temp_path, ignore_errors=True)
            _queue.task_done()
