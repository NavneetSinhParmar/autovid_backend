import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from datetime import datetime
from bson import ObjectId
import json
from app.db.connection import db
from app.utils.auth import require_roles
from app.services.video_renderer import render_preview
import uuid
import os 
router = APIRouter(prefix="/templates", tags=["Templates"])


# ================= CREATE TEMPLATE =================
@router.post("/")
async def create_template(
    data: dict,
    user=Depends(require_roles("company"))
):
    print("User creating template:", user)

    company = await db.companies.find_one({
        "user_id": str(user["_id"])
    })

    print("Creating template for company:", company)

    if not company:
        raise HTTPException(400, "Company not found")

    template_doc = {
        "company_id": str(company["_id"]),
        "template_name": data["template_name"],
        "category": data.get("category", "general"),
        "base_video_url": data.get("base_video_url"),
        "base_image_url": data.get("base_image_url"),
        "base_audio_url": data.get("base_audio_url"),
        "duration": data.get("duration"),
        "trim": data.get("trim"),
        "template_json": data["template_json"],
        "type": data.get("type", "video"),
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await db.templates.insert_one(template_doc)

    return {
        "message": "Template created successfully",
        "template_id": str(result.inserted_id)
    }


# ================= LIST TEMPLATES =================
@router.get("/")
async def list_templates(user=Depends(require_roles("company"))):

    company = await db.companies.find_one({
        "user_id": str(user["_id"])
    })

    templates = await db.templates.find({
        "company_id": str(company["_id"]),
        "status": "active"
    }).to_list(length=1000)

    for t in templates:
        t["id"] = str(t["_id"])
        del t["_id"]

    return {"templates": templates}


# ================= GET TEMPLATE =================
@router.get("/{template_id}")
async def get_template(template_id: str):

    template = await db.templates.find_one({
        "_id": ObjectId(template_id),
        "status": "active"
    })

    if not template:
        raise HTTPException(404, "Template not found")

    template["id"] = str(template["_id"])
    del template["_id"]

    return {"template": template}


# ================= UPDATE TEMPLATE (PATCH) =================
@router.patch("/{template_id}")
async def update_template(
    template_id: str,
    data: dict,
    user=Depends(require_roles("company"))
):
    await db.templates.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {**data, "updated_at": datetime.utcnow()}}
    )

    return {"message": "Template updated successfully"}


# ================= DELETE TEMPLATE =================
@router.delete("/{template_id}")
async def delete_template(template_id: str):

    await db.templates.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {"status": "deleted"}}
    )

    return {"message": "Template deleted"}


# ================= PREVIEW TEMPLATE =================
@router.post("/{template_id}/preview")
async def preview_template(template_id: str):

    template = await db.templates.find_one({"_id": ObjectId(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template does not exist")

    media_dir = os.path.abspath("media")
    os.makedirs(media_dir, exist_ok=True)

    preview_filename = f"{template_id}_{uuid.uuid4().hex}_preview.mp4"
    preview_path = os.path.join(media_dir, preview_filename)

    try:
        await run_in_threadpool(
            render_preview,
            template["template_json"],
            {},  # no customer
            preview_path
        )

        return FileResponse(
            preview_path,
            media_type="video/mp4",
            filename=preview_filename
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{template_id}/preview/{customer_id}")
async def preview_template_customer(template_id: str, customer_id: str):

    template = await db.templates.find_one({"_id": ObjectId(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template does not exist")

    customer = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer does not exist")

    media_dir = os.path.abspath("media")
    os.makedirs(media_dir, exist_ok=True)

    preview_filename = f"{template_id}_{customer_id}_{uuid.uuid4().hex}.mp4"
    preview_path = os.path.join(media_dir, preview_filename)

    try:
        await run_in_threadpool(
            render_preview,
            template["template_json"],
            customer,
            preview_path
        )

        return FileResponse(
            preview_path,
            media_type="video/mp4",
            filename=preview_filename
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{template_id}/download/{customer_id}")
async def download_video(template_id: str, customer_id: str):

    filename = f"{template_id}_{customer_id}_preview.mp4"
    file_path = os.path.abspath(os.path.join("media", filename))

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Video file does not exist. You must first generate a preview."
        )

    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename
    )