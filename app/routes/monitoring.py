import os
import shutil
import time
import asyncio

from fastapi import APIRouter, Depends

from app.db.connection import db
from app.utils.auth import require_roles
from app.services.celery_app import celery_app

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@router.get("/metrics")
async def metrics(user=Depends(require_roles("superadmin"))):
    status_counts = {item["_id"]: item["count"] async for item in db.render_jobs.aggregate([
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ])}
    duration_rows = await db.render_jobs.aggregate([
        {"$match": {"status": "COMPLETED", "render_duration": {"$type": "number"}}},
        {"$group": {"_id": "$job_type", "average_seconds": {"$avg": "$render_duration"}, "count": {"$sum": 1}}},
    ]).to_list(None)
    queue_depth = {}
    redis_status = "unavailable"
    try:
        from redis.asyncio import Redis
        redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        await redis.ping()
        redis_status = "ok"
        for queue in ("render_image", "render_video", "tts", "campaigns", "maintenance"):
            queue_depth[queue] = await redis.llen(queue)
        await redis.aclose()
    except Exception:
        queue_depth = {queue: None for queue in ("render_image", "render_video", "tts", "campaigns", "maintenance")}
    usage = shutil.disk_usage(os.getenv("LOCAL_MEDIA_ROOT", "media"))
    active_workers = {}
    try:
        active = await asyncio.to_thread(lambda: celery_app.control.inspect(timeout=1.0).active() or {})
        active_workers = {worker: len(tasks) for worker, tasks in active.items()}
    except Exception:
        active_workers = {}
    return {
        "timestamp": time.time(),
        "render_jobs": status_counts,
        "average_render_time": {row["_id"]: {"seconds": round(row["average_seconds"], 3), "count": row["count"]} for row in duration_rows},
        "queue_depth": queue_depth,
        "active_workers": active_workers,
        "health": {"mongo": "ok", "redis": redis_status},
        "storage": {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free},
    }
