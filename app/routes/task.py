from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from datetime import datetime
from bson import ObjectId

from app.db.connection import db
from app.utils.auth import require_roles
from app.services.render_queue import enqueue_celery_render_job, get_persisted_render_job
from app.core.rate_limit import rate_limit
from app.core.settings import settings
from app.core.tenancy import company_object_id_filter, object_id

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _json_safe_doc(doc: dict) -> dict:
    safe = {}
    for key, value in doc.items():
        if key == "_id":
            safe["id"] = str(value)
        elif isinstance(value, ObjectId):
            safe[key] = str(value)
        else:
            safe[key] = value
    return safe


@router.post("/generate", status_code=202)
async def generate_video(
    template_id: str,
    customer_id: str,
    user=Depends(rate_limit("render-submit", settings.render_rate_limit))
):
    if user.get("role") != "company":
        raise HTTPException(403, "Company access required")
    # 1. Resolve company
    company = await db.companies.find_one({"user_id": str(user["_id"])})
    if not company:
        raise HTTPException(400, "Company not found")

    # 2. Validate template
    template = await db.templates.find_one({
        "_id": object_id(template_id, "template_id"),
        "company_id": str(company["_id"])
    })
    if not template:
        raise HTTPException(404, "Template not found")

    # 3. Validate customer
    customer = await db.customers.find_one({
        "_id": object_id(customer_id, "customer_id"),
        "linked_company_id": company_object_id_filter(str(company["_id"]))
    })
    if not customer:
        raise HTTPException(404, "Customer not found")

    # 4. Create video task
    task_doc = {
        "company_id": str(company["_id"]),
        "template_id": template_id,
        "customer_id": customer_id,
        "status": "QUEUED",
        "progress": 0,
        "output_url": None,
        "error": None,
        "error_details": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await db.video_tasks.insert_one(task_doc)
    task_id = str(result.inserted_id)

    customer_context = {
        "id": customer_id,
        **{k: (v.isoformat() if hasattr(v, "isoformat") else str(v) if v is not None else "") for k, v in customer.items() if k != "_id"},
    }
    company_context = {
        "id": str(company["_id"]),
        **{k: (v.isoformat() if hasattr(v, "isoformat") else str(v) if v is not None else "") for k, v in company.items() if k != "_id"},
    }

    try:
        render_job = await enqueue_celery_render_job(
            kind="task_video_generate",
            extension="mp4",
            video_task_id=task_id,
            company_id=str(company["_id"]),
            customer_id=customer_id,
            template_id=template_id,
            idempotency_key=f"task:{task_id}",
            payload={
                "template": template,
                "context": {"customer": customer_context, "company": company_context},
            },
        )
    except Exception as exc:
        from app.core.errors import AppError
        if isinstance(exc, AppError):
            raise
        raise HTTPException(503, f"Render queue unavailable: {exc}") from exc

    return {
        "message": "Video generation queued",
        "task_id": task_id,
        "job_id": render_job["job_id"],
        "status": render_job["status"],
        "progress": render_job["progress"],
        "status_url": render_job["status_url"],
    }


@router.get("/{task_id}/status")
async def video_task_status(task_id: str, user=Depends(require_roles("company"))):
    company = await db.companies.find_one({"user_id": str(user["_id"])})
    if not company:
        raise HTTPException(400, "Company not found")

    task = await db.video_tasks.find_one({
        "_id": object_id(task_id, "task_id"),
        "company_id": str(company["_id"]),
    })
    if not task:
        raise HTTPException(404, "Task not found")

    task = _json_safe_doc(task)
    job = None
    if task.get("render_job_id"):
        job = await get_persisted_render_job(task["render_job_id"])
    return jsonable_encoder({"task": task, "render_job": job})
