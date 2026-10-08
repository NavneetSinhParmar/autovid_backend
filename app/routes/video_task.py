from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
import asyncio
import shutil
from copy import deepcopy

from app.db.connection import db
from app.utils.auth import require_roles
from fastapi.responses import FileResponse
import os
import json
from app.services.video_renderer import render_preview
from app.services.storage import ensure_media_folder, get_media_abs_path, template_folder_path
from app.services.render_queue import enqueue_celery_render_job
from app.core.tenancy import company_id_for_user, company_object_id_filter, object_id
from app.core.rate_limit import rate_limit
from app.core.settings import settings
from app.core.pagination import PaginationParams, page_result


router = APIRouter(prefix="/video-task", tags=["Video Task"])

@router.get("/all")
async def list_video_tasks(
    pagination: PaginationParams = Depends(),
    user=Depends(require_roles("superadmin", "company"))
):
    query = {}
    if user.get("role") == "company":
        query["company_id"] = await company_id_for_user(user)
    total = await db.video_tasks.count_documents(query)
    tasks = await db.video_tasks.find(query).sort("created_at", -1).skip(pagination.skip).limit(pagination.limit).to_list(pagination.limit)
    for task in tasks:
        task["id"] = str(task.pop("_id"))
    return page_result(tasks, total, pagination)


@router.post("/generate")
async def generate_video(
    template_id: str,
    customer_id: str,
    user=Depends(require_roles("company"))
):
    company = await db.companies.find_one({"user_id": str(user["_id"])})
    if not company:
        raise HTTPException(404, "Company not found")
    company_id = str(company["_id"])
    template = await db.templates.find_one({"_id": object_id(template_id, "template_id"), "company_id": company_id})
    customer = await db.customers.find_one({
        "_id": object_id(customer_id, "customer_id"),
        "linked_company_id": company_object_id_filter(company_id),
    })
    if not template or not customer:
        raise HTTPException(404, "Template or customer not found")

    task_doc = {
        "company_id": company_id,
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
    company_id = await company_id_for_user(user)
    task = await db.video_tasks.find_one({"_id": object_id(task_id, "task_id"), "company_id": company_id})
    if not task:
        raise HTTPException(404, "Task not found")

    task["id"] = str(task["_id"])
    del task["_id"]

    return {"task": task}

def normalize_doc(doc: dict | None) -> dict:
    if not doc:
        return {}
    safe = {}
    for k, v in doc.items():
        if k == "_id":
            safe["id"] = str(v)
        elif hasattr(v, "isoformat"):
            safe[k] = v.isoformat()
        else:
            safe[k] = str(v) if v is not None else ""
    return safe

async def hydrate_company_email(company: dict | None) -> dict | None:
    if not company or company.get("email"):
        return company

    user_id = company.get("user_id")
    if not user_id:
        return company

    try:
        user_doc = await db.users.find_one({"_id": ObjectId(str(user_id))}, {"email": 1})
    except Exception:
        user_doc = await db.users.find_one({"_id": str(user_id)}, {"email": 1})

    if user_doc and user_doc.get("email"):
        company["email"] = user_doc["email"]
    return company


@router.post(
    "/public/video/{template_id}/{customer_id}",
    status_code=202,
)
async def public_video_download(
    template_id: str,
    customer_id: str,
    _=Depends(rate_limit("public-video-render", settings.render_rate_limit, authenticated=False)),
):
    # 1️⃣ Fetch template
    template = await db.templates.find_one({"_id": object_id(template_id, "template_id"), "public": True, "status": "active"})
    if not template:
        raise HTTPException(404, "Template not found")

    # 2️⃣ Fetch customer
    customer = await db.customers.find_one({"_id": object_id(customer_id, "customer_id")})
    if not customer:
        raise HTTPException(404, "Customer not found")

    company_id = str(template.get("company_id") or "")
    if not company_id or customer.get("linked_company_id") not in {company_id, ObjectId(company_id)}:
        raise HTTPException(404, "Template and customer do not belong to the same company")
    customer_context = normalize_doc(customer)
    company_doc = await db.companies.find_one({"_id": ObjectId(company_id)})
    company_doc = await hydrate_company_email(company_doc)
    company_context = normalize_doc(company_doc)
    job = await enqueue_celery_render_job(
        kind="public_video_task_download",
        extension="mp4",
        company_id=company_id,
        customer_id=customer_id,
        template_id=template_id,
        public_access=True,
        payload={"template": template, "context": {"customer": customer_context, "company": company_context}},
    )
    return {"message": "Video render queued", **job}
