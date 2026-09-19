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
from app.services.render_queue import run_render_job


router = APIRouter(prefix="/video-task", tags=["Video Task"])

@router.get("/all")
async def list_video_tasks(
    user=Depends(require_roles("superadmin", "company"))
):
    tasks = await db.video_tasks.find().to_list(100)
    return tasks


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


@router.get(
    "/public/video/{template_id}/{customer_id}",
    response_class=FileResponse
)
async def public_video_download(
    template_id: str,
    customer_id: str
):
    # 1️⃣ Fetch template
    template = await db.templates.find_one({"_id": ObjectId(template_id)})
    if not template:
        raise HTTPException(404, "Template not found")

    # 2️⃣ Fetch customer
    customer = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not customer:
        raise HTTPException(404, "Customer not found")

    customer = normalize_doc(customer)
    company = {}
    company_id = template.get("company_id") or customer.get("linked_company_id")
    if company_id:
        company_doc = await db.companies.find_one({"_id": ObjectId(str(company_id))})
        company_doc = await hydrate_company_email(company_doc)
        company = normalize_doc(company_doc)

    # 4️⃣ Prepare output
    filename = f"{template_id}_{customer_id}_preview.mp4"
    folder = ensure_media_folder(
        template.get("folder_path") or template_folder_path(str(company_id), template_id)
    )
    output_path = get_media_abs_path(f"{folder}/{filename}")

    # 5️⃣ Render only if not exists
    if not os.path.exists(output_path):
        template_snapshot = deepcopy(template)
        customer_snapshot = deepcopy(customer)
        company_snapshot = deepcopy(company)

        async def work(job_id: str, job_output_path: str, _folder: str):
            await asyncio.to_thread(
                render_preview,
                deepcopy(template_snapshot),
                {"customer": deepcopy(customer_snapshot), "company": deepcopy(company_snapshot)},
                job_output_path,
            )
            shutil.copyfile(job_output_path, output_path)

        await run_render_job(kind="public_video_task_download", extension="mp4", work=work)

        # 6️⃣ Create video task entry
        await db.video_tasks.insert_one({
            "template_id": ObjectId(template_id),
            "customer_id": ObjectId(customer_id),
            "video_path": f"/media/{folder}/{filename}",
            "download_count": 0,
            "is_public": True,
            "created_at": datetime.utcnow()
        })

    # 7️⃣ Increment download count
    await db.video_tasks.update_one(
        {
            "template_id": ObjectId(template_id),
            "customer_id": ObjectId(customer_id)
        },
        {"$inc": {"download_count": 1}}
    )

    # 8️⃣ Return video
    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=filename
    )
