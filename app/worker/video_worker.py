from celery import Celery
from datetime import datetime
from bson import ObjectId
from app.services.video_renderer import render_video
from app.db.connection import db

celery_app = Celery(
    "video_worker",
    broker="redis://localhost:6379/0"
)

@celery_app.task
def render_video_task(task_id: str):
    try:
        db.video_tasks.update_one(
            {"_id": ObjectId(task_id)},
            {"$set": {"status": "processing", "updated_at": datetime.utcnow()}}
        )

        output = render_video(task_id)

        db.video_tasks.update_one(
            {"_id": ObjectId(task_id)},
            {"$set": {
                "status": "completed",
                "progress": 100,
                "output_video_url": output,
                "updated_at": datetime.utcnow()
            }}
        )

    except Exception as e:
        db.video_tasks.update_one(
            {"_id": ObjectId(task_id)},
            {"$set": {
                "status": "failed",
                "error": str(e),
                "updated_at": datetime.utcnow()
            }}
        )
