from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId

from app.db.connection import db
from app.utils.auth import require_roles
from app.workers.video_worker import start_video_render

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("/generate")
async def generate_video(
    template_id: str,
    customer_id: str,
    user=Depends(require_roles("company"))
):
    # 1. Resolve company
    company = await db.companies.find_one({"user_id": str(user["_id"])})
    if not company:
        raise HTTPException(400, "Company not found")

    # 2. Validate template
    template = await db.templates.find_one({
        "_id": ObjectId(template_id),
        "company_id": str(company["_id"])
    })
    if not template:
        raise HTTPException(404, "Template not found")

    # 3. Validate customer
    customer = await db.customers.find_one({
        "_id": ObjectId(customer_id),
        "linked_company_id": str(company["_id"])
    })
    if not customer:
        raise HTTPException(404, "Customer not found")

    # 4. Create video task
    task_doc = {
        "company_id": str(company["_id"]),
        "template_id": template_id,
        "customer_id": customer_id,
        "status": "pending",
        "output_url": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await db.video_tasks.insert_one(task_doc)
    task_id = str(result.inserted_id)

    # 5. Start background rendering
    start_video_render(task_id)

    return {
        "message": "Video generation started",
        "task_id": task_id
    }
