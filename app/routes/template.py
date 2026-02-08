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

    template_json = data.get("template_json", {})
    design = template_json.get("design", {}) if isinstance(template_json, dict) else {}
    options = template_json.get("options", {}) if isinstance(template_json, dict) else {}
    if isinstance(design, dict):
        if "fps" not in design and isinstance(options, dict) and "fps" in options:
            design["fps"] = options["fps"]
        if "size" not in design:
            design["size"] = {"width": 1920, "height": 1080}
        template_json["design"] = design

    template_doc = {
        "company_id": str(company["_id"]),
        "template_name": data["template_name"],
        "category": data.get("category", "general"),
        "base_video_url": data.get("base_video_url"),
        "base_image_url": data.get("base_image_url"),
        "base_audio_url": data.get("base_audio_url"),
        "duration": data.get("duration"),
        "trim": data.get("trim"),
        "template_json": template_json,
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
        raise HTTPException(status_code=404, detail="Template Does not exist!")

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
    print("Preview Of Filename is",preview_filename)
    preview_path = os.path.join(media_dir, preview_filename)
    print("Preview path is is",preview_filename)

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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^}]+)\s*}}")
def get_nested_value(data: dict, path: str):
    """
    Supports dot notation like:
    user.email
    company.company_name
    """
    try:
        for key in path.split("."):
            data = data.get(key)
            if data is None:
                return ""
        return str(data)
    except Exception:
        return ""

# def replace_placeholders(template_json: dict, customer: dict) -> dict:
#     template_str = json.dumps(template_json)

#     replacements = {
#         "{{customer_company_name}}": customer.get("customer_company_name", ""),
#         "{{full_name}}": customer.get("full_name", ""),
#         "{{city}}": customer.get("city", ""),
#         "{{phone_number}}": customer.get("phone_number", "")
#     }

#     for key, value in replacements.items():
#         template_str = template_str.replace(key, value)

#     return json.loads(template_str)

def replace_placeholders(data, customer):
    # Pure JSON object ko string bana kar replace karna sabse safe hai
    json_str = json.dumps(data)
    for key, value in customer.items():
        # Case-insensitive replacement for {{name}}, {{Name}}, etc.
        placeholder = "{{" + str(key) + "}}"
        json_str = json_str.replace(placeholder, str(value))
    return json.loads(json_str)


def normalize_customer(customer: dict) -> dict:
    safe = {}
    for k, v in customer.items():
        if k == "_id":
            safe["id"] = str(v)
        elif hasattr(v, "isoformat"):
            safe[k] = v.isoformat()
        else:
            safe[k] = str(v) if v is not None else ""
    return safe

def normalize_company(company: dict | None) -> dict:
    if not company:
        return {}

    return {
        "company_name": company.get("company_name", ""),
        "description": company.get("description", ""),        
        "mobile": company.get("mobile", ""),        
        "logo_url": company.get("logo_url", ""),   # image path / url
    }

@router.post("/{template_id}/preview/{customer_id}")
async def preview_template_customer(template_id: str, customer_id: str):

    template = await db.templates.find_one({"_id": ObjectId(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template does not exist")

    customer = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer does not exist")

    customer = normalize_customer(customer)

    # ✅ FETCH COMPANY
    company = None
    if customer.get("linked_company_id"):
        company = await db.companies.find_one({
            "_id": ObjectId(customer["linked_company_id"])
        })

    company = normalize_company(company) if company else {}

    media_dir = os.path.abspath("media")
    os.makedirs(media_dir, exist_ok=True)

    template_type = template.get("type", "video")

    # # 🔀 IMAGE
    # if template_type == "image":
    #     preview_filename = f"{template_id}_{customer_id}_preview.png"
    #     preview_path = os.path.join(media_dir, preview_filename)

    #     await run_in_threadpool(
    #         render_image_preview,
    #         template["template_json"],
    #         {
    #             "customer": customer,
    #             "company": company
    #         },
    #         preview_path
    #     )

    #     return FileResponse(preview_path, media_type="image/png")

    # 🎥 VIDEO
    preview_filename = f"{template_id}_{customer_id}_preview.mp4"
    preview_path = os.path.join(media_dir, preview_filename)

    await run_in_threadpool(
        render_preview,
        template["template_json"],
        {
            "customer": customer,
            "company": company
        },
        preview_path
    )

    return FileResponse(preview_path, media_type="video/mp4")

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