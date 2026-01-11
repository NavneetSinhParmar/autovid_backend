from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
import uuid

from app.db.connection import db
from app.utils.auth import require_roles
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
import os
import json
from app.services.video_renderer import render_preview


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

def replace_placeholders(template_json: dict, customer: dict) -> dict:
    template_str = json.dumps(template_json)

    replacements = {
        "{{customer_company_name}}": customer.get("customer_company_name", ""),
        "{{full_name}}": customer.get("full_name", ""),
        "{{city}}": customer.get("city", ""),
        "{{phone_number}}": customer.get("phone_number", "")
    }

    for key, value in replacements.items():
        template_str = template_str.replace(key, value)

    return json.loads(template_str)


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

    # 3️⃣ Replace placeholders
    template["template_json"] = replace_placeholders(
        template["template_json"],
        customer
    )

    # 4️⃣ Prepare output
    media_dir = os.path.abspath("media")
    os.makedirs(media_dir, exist_ok=True)

    filename = f"{template_id}_{customer_id}.mp4"
    output_path = os.path.join(media_dir, filename)

    # 5️⃣ Render only if not exists
    if not os.path.exists(output_path):
        await run_in_threadpool(render_preview, template, output_path)

        # 6️⃣ Create video task entry
        await db.video_tasks.insert_one({
            "template_id": ObjectId(template_id),
            "customer_id": ObjectId(customer_id),
            "video_path": f"/media/{filename}",
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
