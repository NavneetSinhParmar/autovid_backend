import logging
import os
import shutil
import traceback
from copy import deepcopy
from datetime import datetime

from bson import ObjectId

from app.services.celery_app import celery_app
from app.services.render_queue import current_render_job_id, current_render_temp_dir
from app.services.storage import ensure_media_folder, get_media_abs_path
from app.services.sync_db import sync_db
from app.services.url import build_media_url
from app.services.video_renderer import render_preview

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.utcnow()


def _task_filter(video_task_id: str | None) -> dict | None:
    if not video_task_id:
        return None
    return {"_id": ObjectId(video_task_id)}


def _set_job(job_id: str, values: dict) -> None:
    values["updated_at"] = _now()
    sync_db.render_jobs.update_one({"job_id": job_id}, {"$set": values})


def _set_task(video_task_id: str | None, values: dict) -> None:
    filt = _task_filter(video_task_id)
    if not filt:
        return
    values["updated_at"] = _now()
    sync_db.video_tasks.update_one(filt, {"$set": values})


def _safe_cleanup_tmp(tmp_folder: str | None) -> None:
    if not tmp_folder:
        return
    tmp_path = get_media_abs_path(tmp_folder)
    media_root = os.path.abspath(os.getenv("LOCAL_MEDIA_ROOT", "./media"))
    tmp_path_abs = os.path.abspath(tmp_path)
    if os.path.commonpath([media_root, tmp_path_abs]) != media_root:
        raise ValueError("Refusing to delete temp path outside media root")
    if os.path.basename(tmp_path_abs) != "tmp":
        raise ValueError("Refusing to delete non-job temp directory")
    shutil.rmtree(tmp_path_abs, ignore_errors=True)


@celery_app.task(
    bind=True,
    name="app.worker.video_worker.render_video_task",
    autoretry_for=(),
)
def render_video_task(self, job_id: str):
    job = sync_db.render_jobs.find_one({"job_id": job_id})
    if not job:
        raise ValueError(f"Render job not found: {job_id}")

    video_task_id = job.get("video_task_id")
    folder = job.get("folder")
    tmp_folder = job.get("tmp_folder")
    output_relative = job.get("output_relative_path") or f"{folder}/output.mp4"

    ensure_media_folder(folder)
    ensure_media_folder(tmp_folder)
    output_path = get_media_abs_path(output_relative)
    tmp_path = get_media_abs_path(tmp_folder)

    token_job = current_render_job_id.set(job_id)
    token_tmp = current_render_temp_dir.set(tmp_path)

    started = _now()
    _set_job(job_id, {
        "status": "PROCESSING",
        "progress": max(int(job.get("progress") or 0), 5),
        "started_at": job.get("started_at") or started,
        "celery_task_id": self.request.id,
        "worker_hostname": self.request.hostname,
    })
    _set_task(video_task_id, {
        "status": "PROCESSING",
        "progress": max(int(job.get("progress") or 0), 5),
        "render_job_id": job_id,
    })

    try:
        payload = job.get("payload") or {}
        template = deepcopy(payload.get("template") or {})
        context = deepcopy(payload.get("context") or {})
        if not template:
            raise ValueError("Render job payload is missing template data")

        render_preview(template, context, output_path)

        output_url = build_media_url(output_relative)
        completed = _now()
        _set_job(job_id, {
            "status": "COMPLETED",
            "progress": 100,
            "output_url": output_url,
            "output_path": output_path,
            "completed_at": completed,
            "error": None,
            "error_details": None,
        })
        _set_task(video_task_id, {
            "status": "COMPLETED",
            "progress": 100,
            "output_url": output_url,
            "output_video_url": output_url,
            "error": None,
            "error_details": None,
        })
        logger.info("[celery_render] job_id=%s completed", job_id)
        return {"job_id": job_id, "status": "COMPLETED", "output_url": output_url}
    except Exception as exc:
        details = {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }
        _set_job(job_id, {
            "status": "FAILED",
            "error": str(exc),
            "error_details": details,
            "failed_at": _now(),
        })
        _set_task(video_task_id, {
            "status": "FAILED",
            "error": str(exc),
            "error_details": details,
        })
        logger.exception("[celery_render] job_id=%s failed", job_id)
        raise
    finally:
        current_render_job_id.reset(token_job)
        current_render_temp_dir.reset(token_tmp)
        _safe_cleanup_tmp(tmp_folder)
