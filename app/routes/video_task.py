from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
import uuid

from app.db.connection import db
from app.utils.auth import require_roles

router = APIRouter(prefix="/video-task", tags=["Video Task"])

@router.post("/generate")
async def generate_video(
    template_id: str,
    customer_id: str,
    user=Depends(require_roles("company"))
):
    company = await db.companies.find_one({"user_id": str(user["_id"])})
    if not company:
        raise HTTPException(404, "Company not found")

    task_doc = {
        "company_id": str(company["_id"]),
        "customer_id": customer_id,
        "template_id": template_id,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    result = await db.video_tasks.insert_one(task_doc)
    task_id = str(result.inserted_id)

    # 🔐 Create private link (company)
    private_link = f"/video-task/private/{task_id}"

    return {
        "message": "Video task created",
        "task_id": task_id,
        "private_link": private_link
    }

@router.get("/private/{task_id}")
async def private_video(task_id: str, user=Depends(require_roles("company"))):

    task = await db.video_tasks.find_one({"_id": ObjectId(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")

    task["id"] = str(task["_id"])
    del task["_id"]

    return {"task": task}
