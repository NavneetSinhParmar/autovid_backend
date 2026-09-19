import asyncio
import contextvars
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Any

from app.services.storage import ensure_media_folder, get_media_abs_path
from app.services.url import build_media_url

logger = logging.getLogger(__name__)

RENDER_JOB_ROOT = os.getenv("RENDER_JOB_ROOT", "render_jobs")
RENDER_QUEUE_BACKEND = os.getenv("RENDER_QUEUE_BACKEND", "memory").lower()

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
_worker_tasks: list[asyncio.Task] = []
_sequence = 0


def _now() -> datetime:
    return datetime.utcnow()


def normalize_render_status(status: str | None) -> str:
    return (status or "QUEUED").upper()


async def enqueue_celery_render_job(
    *,
    kind: str,
    extension: str,
    video_task_id: str | None = None,
    payload: dict | None = None,
) -> dict:
    from bson import ObjectId

    from app.db.connection import db
    from app.services.celery_app import celery_app

    job_id = uuid.uuid4().hex
    extension = extension.lstrip(".")
    folder = f"{RENDER_JOB_ROOT}/{job_id}"
    tmp_folder = f"{folder}/tmp"
    ensure_media_folder(tmp_folder)

    now = _now()
    output_relative = f"{folder}/output.{extension}"
    status = {
        "job_id": job_id,
        "kind": kind,
        "status": "QUEUED",
        "progress": 0,
        "video_task_id": video_task_id,
        "folder": folder,
        "tmp_folder": tmp_folder,
        "output_relative_path": output_relative,
        "output_url": None,
        "error": None,
        "error_details": None,
        "created_at": now,
        "queued_at": now,
        "started_at": None,
        "completed_at": None,
        "failed_at": None,
        "updated_at": now,
        "status_url": f"/render-jobs/{job_id}",
        "download_url": f"/render-jobs/{job_id}/download",
        "payload": payload or {},
    }
    await db.render_jobs.insert_one(status.copy())

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
        celery_app.send_task("app.worker.video_worker.render_video_task", args=[job_id])
    except Exception as exc:
        failed_at = _now()
        error = f"Failed to enqueue render job: {exc}"
        await db.render_jobs.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "FAILED",
                "error": error,
                "error_details": {"type": exc.__class__.__name__, "message": str(exc)},
                "failed_at": failed_at,
                "updated_at": failed_at,
            }},
        )
        if video_task_id:
            await db.video_tasks.update_one(
                {"_id": ObjectId(video_task_id)},
                {"$set": {
                    "status": "FAILED",
                    "error": error,
                    "error_details": {"type": exc.__class__.__name__, "message": str(exc)},
                    "updated_at": failed_at,
                }},
            )
        raise
    status.pop("payload", None)
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


def _render_concurrency() -> int:
    try:
        return max(1, int(os.getenv("FFMPEG_WORKER_CONCURRENCY", "2")))
    except ValueError:
        logger.warning(
            "Invalid FFMPEG_WORKER_CONCURRENCY=%r; using 2",
            os.getenv("FFMPEG_WORKER_CONCURRENCY"),
        )
        return 2


def enforce_single_worker_for_memory_queue() -> None:
    if RENDER_QUEUE_BACKEND == "memory" and _configured_worker_count() != 1:
        raise RuntimeError(
            "The in-memory render queue requires one app worker. "
            "Set WEB_CONCURRENCY=1 / --workers 1, or replace it with Redis/shared queue."
        )


def start_render_worker() -> None:
    global _worker_tasks
    enforce_single_worker_for_memory_queue()
    _worker_tasks = [task for task in _worker_tasks if not task.done()]
    if _worker_tasks:
        return
    concurrency = _render_concurrency()
    _worker_tasks = [
        asyncio.get_running_loop().create_task(_render_worker(worker_number))
        for worker_number in range(1, concurrency + 1)
    ]
    logger.info("[render_queue] FIFO render workers started concurrency=%s", concurrency)


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

    job = await db.render_jobs.find_one({"job_id": job_id}, {"payload": 0})
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


async def _render_worker(worker_number: int) -> None:
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
            logger.info(
                "[render_queue] worker=%s job_id=%s sequence=%s processing",
                worker_number,
                job.job_id,
                job.sequence,
            )
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
