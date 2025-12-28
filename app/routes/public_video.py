from fastapi import APIRouter, HTTPException
from datetime import datetime
from bson import ObjectId
import uuid

from app.db.connection import db

router = APIRouter(prefix="/public-video", tags=["Public Video"])

@router.post("/create/{task_id}")
async def create_public_link(task_id: str):

    task = await db.video_tasks.find_one({"_id": ObjectId(task_id)})
    if not task:
        raise HTTPException(404, "Video task not found")

    token = uuid.uuid4().hex

    link_doc = {
        "video_task_id": task_id,
        "token": token,
        "is_active": True,
        "created_at": datetime.utcnow()
    }

    await db.public_video_links.insert_one(link_doc)

    return {
        "public_link": f"/public-video/watch/{token}"
    }

@router.get("/watch/{token}")
async def watch_video(token: str):

    link = await db.public_video_links.find_one({
        "token": token,
        "is_active": True
    })

    if not link:
        raise HTTPException(404, "Invalid or expired link")

    task = await db.video_tasks.find_one({
        "_id": ObjectId(link["video_task_id"])
    })

    if not task:
        raise HTTPException(404, "Video not found")

    return {
        "status": task["status"],
        "video_url": task.get("output_url")
    }
