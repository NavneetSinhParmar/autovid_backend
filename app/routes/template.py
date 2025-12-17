from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId

from app.db.connection import db
from app.utils.auth import require_roles
from app.models.template_model import Template

router = APIRouter(prefix="/templates", tags=["Templates"])

@router.post("/")
async def create_template(
    data: dict,
    user=Depends(require_roles("company"))
):
    # find company of logged-in user
    company = await db.companies.find_one({"user_id": user["id"]})
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
        "template_json": data["template_json"],  # STORE AS IS
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await db.templates.insert_one(template_doc)

    return {
        "message": "Template created successfully",
        "template_id": str(result.inserted_id)
    }

@router.get("/")
async def list_templates(user=Depends(require_roles("company"))):

    company = await db.companies.find_one({"user_id": user["id"]})

    templates = await db.templates.find({
        "company_id": str(company["_id"]),
        "status": "active"
    }).to_list(length=1000)

    for t in templates:
        t["id"] = str(t["_id"])
        del t["_id"]

    return {"templates": templates}

@router.get("/{template_id}")
async def get_template(template_id: str, user=Depends(require_roles("company"))):

    template = await db.templates.find_one({"_id": ObjectId(template_id)})

    if not template:
        raise HTTPException(404, "Template not found")

    template["id"] = str(template["_id"])
    del template["_id"]

    return {"template": template}

@router.put("/{template_id}")
async def update_template(
    template_id: str,
    data: dict,
    user=Depends(require_roles("company"))
):
    await db.templates.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {
            "template_name": data.get("template_name"),
            "category": data.get("category"),
            "base_video_url": data.get("base_video_url"),
            "base_image_url": data.get("base_image_url"),
            "base_audio_url": data.get("base_audio_url"),
            "duration": data.get("duration"),
            "trim": data.get("trim"),
            "template_json": data.get("template_json"),
            "updated_at": datetime.utcnow()
        }}
    )

    return {"message": "Template updated successfully"}

@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    user=Depends(require_roles("company"))
):
    await db.templates.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {"status": "deleted"}}
    )

    return {"message": "Template deleted"}
