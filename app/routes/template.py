from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId

from app.db.connection import db
from app.utils.auth import require_roles
import subprocess
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




@router.post("/{template_id}/preview")
async def preview_template(
    template_id: str,
    user=Depends(require_roles("company"))
):
    template = await db.templates.find_one({"_id": ObjectId(template_id)})
    print("Generating preview for template:", template)

    pass

    if not template:
        raise HTTPException(404, "Template not found")

    # ---- STEP 1: Get base video ----
    base_video = template.get("base_video_url")
    if not base_video:
        raise HTTPException(400, "Base video not found")

    # ---- STEP 2: Create preview output ----
    preview_path = f"./media/{template_id}_preview.mp4"
    print("Generating preview at:", preview_path)

    # ---- STEP 3: FFmpeg preview command (2 sec only) ----
    ffmpeg_exe = r'C:\ffmpeg-2025-12-28-git-9ab2a437a1-full_build\bin\ffmpeg.exe'

# 2. Construct the command list carefully
    cmd = [
        ffmpeg_exe, 
        '-y', 
        '-i', base_video, 
        '-t', '2', 
        '-vf', 'scale=720:1280', 
        preview_path
    ]

    # 3. Run it
    print(f"DEBUG: Running command: {cmd}")   
    subprocess.run(cmd, check=True)

    # ---- STEP 4: Save preview url ----
    await db.templates.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {"preview_url": preview_path}}
    )

    return {
        "message": "Preview generated",
        "preview_url": preview_path
    }
