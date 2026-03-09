from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from bson import ObjectId
import os

from app.db.connection import db
from app.services.video_renderer import render_preview, render_image_preview

router = APIRouter(prefix="/public/templates", tags=["Public Templates"])


def normalize_customer(customer: dict) -> dict:
    safe = {}
    for k, v in customer.items():
        if hasattr(v, "isoformat"):
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
        "logo_url": company.get("logo_url", ""),
    }


# ================= PUBLIC PREVIEW =================
@router.post("/{template_id}/preview")
async def public_preview(template_id: str, data: dict):

    template = await db.templates.find_one({
        "_id": ObjectId(template_id),
        "public": True,
        "status": "active"
    })

    if not template:
        raise HTTPException(status_code=404, detail="Template not available")

    customer = normalize_customer(data.get("customer", {}))

    company = None
    company_id = template.get("company_id")

    if company_id:
        company = await db.companies.find_one({"_id": ObjectId(company_id)})

    company = normalize_company(company)

    media_dir = os.path.abspath("media")
    os.makedirs(media_dir, exist_ok=True)

    template_type = str(template.get("type", "video")).lower()

    # IMAGE TEMPLATE
    if template_type in ("img", "image"):

        filename = f"{template_id}_public_preview.jpg"
        preview_path = os.path.join(media_dir, filename)

        await run_in_threadpool(
            render_image_preview,
            template["template_json"],
            customer,
            company,
            preview_path
        )

        return FileResponse(
            preview_path,
            media_type="image/jpeg",
            filename=filename
        )

    # VIDEO TEMPLATE
    filename = f"{template_id}_public_preview.mp4"
    preview_path = os.path.join(media_dir, filename)

    await run_in_threadpool(
        render_preview,
        template,
        {
            "customer": customer,
            "company": company
        },
        preview_path
    )

    return FileResponse(
        preview_path,
        media_type="video/mp4",
        filename=filename
    )