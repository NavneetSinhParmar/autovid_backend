from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from bson import ObjectId
import os

from app.db.connection import db
from app.services.video_renderer import render_preview, render_image_preview
from copy import deepcopy

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
    fields = data.get("fields", {}) or {}

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

        tpl_json = deepcopy(template.get("template_json", {}))

        replacements = _apply_fields_to_template(
            tpl_json, fields, customer, company
        )

        await run_in_threadpool(
            render_image_preview,
            tpl_json,
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

    full_template = deepcopy(template)

    tpl_json = full_template.get("template_json", {}) or {}
    replacements = _apply_fields_to_template(
        tpl_json, fields, customer, company
    )

    full_template["template_json"] = tpl_json

    await run_in_threadpool(
        render_preview,
        full_template,
        {
            "customer": customer,
            "company": company
        },
        preview_path
    )

    return {
        "preview_path": preview_path,
        "filename": filename,
        "replacements": replacements,
        "preview_mode": "video"
    }

@router.post("/{template_id}/download")
async def public_download(template_id: str, data: dict):

    template = await db.templates.find_one({
        "_id": ObjectId(template_id),
        "public": True,
        "status": "active"
    })

    if not template:
        raise HTTPException(status_code=404, detail="Template not available")

    customer = normalize_customer(data.get("customer", {}))
    fields = data.get("fields", {}) or {}

    company = None
    company_id = template.get("company_id")

    if company_id:
        company = await db.companies.find_one({"_id": ObjectId(company_id)})

    company = normalize_company(company)

    media_dir = os.path.abspath("media")
    os.makedirs(media_dir, exist_ok=True)

    template_type = str(template.get("type", "video")).lower()

    # IMAGE
    if template_type in ("img", "image"):

        filename = f"{template_id}_download.jpg"
        preview_path = os.path.join(media_dir, filename)

        tpl_json = deepcopy(template.get("template_json", {}))

        _apply_fields_to_template(
            tpl_json, fields, customer, company
        )

        await run_in_threadpool(
            render_image_preview,
            tpl_json,
            customer,
            company,
            preview_path
        )

        return FileResponse(
            preview_path,
            media_type="image/jpeg",
            filename=filename
        )

    # VIDEO
    filename = f"{template_id}_download.mp4"
    preview_path = os.path.join(media_dir, filename)

    full_template = deepcopy(template)

    tpl_json = full_template.get("template_json", {}) or {}

    _apply_fields_to_template(
        tpl_json, fields, customer, company
    )

    full_template["template_json"] = tpl_json

    await run_in_threadpool(
        render_preview,
        full_template,
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

def _get_field_value(fields: dict, path: str):
    if not path or not isinstance(fields, dict):
        return None

    def _ci_get(d: dict, key: str):
        if key in d:
            return d[key]
        key_l = str(key).lower()
        for k, v in d.items():
            if str(k).lower() == key_l:
                return v
        return None

    parts = str(path).split(".")
    cur = fields
    for p in parts:
        if not isinstance(cur, dict):
            return None
        val = _ci_get(cur, p)
        if val is None:
            return None
        cur = val
    return cur

def _apply_fields_to_template(
    template_json: dict,
    fields: dict,
    customer: dict | None = None,
    company: dict | None = None
):
    if not isinstance(template_json, dict):
        return []

    design = template_json.get("design", {})
    track_map = design.get("trackItemsMap", {})

    replacements = []

    for tid, item in track_map.items():
        try:
            if not isinstance(item, dict):
                continue

            if item.get("type") != "text":
                continue

            metadata = item.get("metadata", {})

            # Only process dynamic fields
            if not metadata.get("isCustomerField"):
                continue

            field_path = metadata.get("fieldPath") or metadata.get("fieldpath")
            field_label = metadata.get("fieldLabel")

            value = None

            # 1️⃣ Try fieldPath
            if field_path:
                fp = str(field_path).strip()

                if fp.startswith("{{") and fp.endswith("}}"):
                    fp = fp[2:-2].strip()

                value = _get_field_value(fields, fp)

            # 2️⃣ Try fieldLabel
            if value is None and field_label:
                for k, v in fields.items():
                    if str(k).lower() == str(field_label).lower():
                        value = v
                        break

            # 3️⃣ Try customer data
            if value is None and isinstance(customer, dict):
                for k, v in customer.items():
                    if str(k).lower() == str(field_label).lower():
                        value = v
                        break

            # 4️⃣ Try company data
            if value is None and isinstance(company, dict):
                for k, v in company.items():
                    if str(k).lower() == str(field_label).lower():
                        value = v
                        break

            if value is None:
                continue

            details = item.get("details", {})
            old = details.get("text")

            details["text"] = str(value)
            item["details"] = details
            track_map[tid] = item

            replacements.append({
                "id": tid,
                "old": old,
                "new": str(value)
            })

        except Exception:
            continue

    design["trackItemsMap"] = track_map
    template_json["design"] = design

    return replacements