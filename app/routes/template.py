from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from datetime import datetime
from bson import ObjectId

from app.db.connection import db
from app.utils.auth import require_roles
from app.services.video_renderer import render_preview

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
        raise HTTPException(status_code=404, detail="Template nahi mila!")

    # Fetch company name for watermarking
    company_id = template.get("company_id")
    company_name = "Our Company" # Default fallback
    
    if company_id:
        company_data = await db.companies.find_one({"_id": ObjectId(company_id)})
        if company_data:
            company_name = company_data.get("company_name") or company_data.get("name") or "Our Company"

    # 2. Prepare output path
    media_dir = os.path.abspath("media")
    os.makedirs(media_dir, exist_ok=True)
    preview_filename = f"{template_id}_preview.mp4"
    preview_path = os.path.join(media_dir, preview_filename)

    try:
        # 3. Render preview in thread pool
        await run_in_threadpool(render_preview, template, preview_path)
        
        # return {"status": "success", "preview_url": f"/media/{preview_filename}"}
        return FileResponse(
            path=preview_path, 
            media_type="video/mp4", 
            filename=preview_filename
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))