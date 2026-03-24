from fastapi import APIRouter, HTTPException, Body
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from bson import ObjectId
from datetime import datetime
import os
from pymongo import ReturnDocument

from app.db.connection import db
from app.services.video_renderer import render_preview, render_image_preview
from copy import deepcopy

router = APIRouter(prefix="/public/templates", tags=["Public Templates"])


def _template_oid(template_id: str) -> ObjectId:
    if not ObjectId.is_valid(template_id):
        raise HTTPException(status_code=400, detail="Invalid template id")
    return ObjectId(template_id)


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

    # Return the generated file directly so clients receive a usable URL/file
    return FileResponse(
        preview_path,
        media_type="video/mp4",
        filename=filename
    )

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

@router.patch("/{template_id}/increment-download")
async def increment_download_counts(
    template_id: str,
    body: dict = Body(default_factory=dict),
):
    """
    Increment download counters on the templates document.

    Body (all optional):
      - public: bool — if true, +1 public_download_count
      - private: bool — if true, +1 private_download_count
      - increment_public / increment_private — aliases for the booleans

    If body is empty {}, both counters are incremented by 1.
    """
    oid = _template_oid(template_id)

    if not body:
        do_pub, do_prv = True, True
    else:
        pub = body.get("public", body.get("increment_public", False))
        prv = body.get("private", body.get("increment_private", False))
        do_pub = bool(pub)
        do_prv = bool(prv)
        if not do_pub and not do_prv:
            raise HTTPException(
                status_code=400,
                detail="Set public and/or private to true, or send an empty body to increment both",
            )

    inc: dict = {}
    if do_pub:
        inc["public_download_count"] = 1
    if do_prv:
        inc["private_download_count"] = 1

    updated = await db.templates.find_one_and_update(
        {"_id": oid, "status": "active"},
        {"$inc": inc, "$set": {"updated_at": datetime.utcnow()}},
        return_document=ReturnDocument.AFTER,
    )

    if not updated:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "message": "Download counts updated",
        "template_id": template_id,
        "public_download_count": int(updated.get("public_download_count") or 0),
        "private_download_count": int(updated.get("private_download_count") or 0),
    }


@router.patch("/{template_id}/increment-download/public")
async def increment_public_download(template_id: str):
    """+1 public_download_count; template must be active and public."""
    oid = _template_oid(template_id)

    updated = await db.templates.find_one_and_update(
        {"_id": oid, "status": "active", "public": True},
        {
            "$inc": {"public_download_count": 1},
            "$set": {"updated_at": datetime.utcnow()},
        },
        return_document=ReturnDocument.AFTER,
    )

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Template not found or not a public active template",
        )

    return {
        "message": "Public download count incremented",
        "template_id": template_id,
        "public_download_count": int(updated.get("public_download_count") or 0),
        "private_download_count": int(updated.get("private_download_count") or 0),
    }


@router.patch("/{template_id}/increment-download/private")
async def increment_private_download(template_id: str):
    """+1 private_download_count; template must be active."""
    oid = _template_oid(template_id)

    updated = await db.templates.find_one_and_update(
        {"_id": oid, "status": "active"},
        {
            "$inc": {"private_download_count": 1},
            "$set": {"updated_at": datetime.utcnow()},
        },
        return_document=ReturnDocument.AFTER,
    )

    if not updated:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "message": "Private download count incremented",
        "template_id": template_id,
        "public_download_count": int(updated.get("public_download_count") or 0),
        "private_download_count": int(updated.get("private_download_count") or 0),
    }


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

            # TEXT replacement (existing behavior)
            if item.get("type") == "text":
                old = details.get("text")
                details["text"] = str(value)
                item["details"] = details
                track_map[tid] = item
                replacements.append({
                    "id": tid,
                    "old": old,
                    "new": str(value)
                })
                continue

            # MEDIA replacement: replace common keys that hold file paths/urls
            old_vals = {}
            replaced = False
            for k, v in list(details.items()):
                lk = str(k).lower()
                if any(sub in lk for sub in ("url", "src", "file", "path", "poster", "image", "video")):
                    old_vals[k] = v
                    details[k] = str(value)
                    replaced = True

            if replaced:
                item["details"] = details
                track_map[tid] = item
                replacements.append({
                    "id": tid,
                    "old": old_vals,
                    "new": str(value)
                })

        except Exception:
            continue

    design["trackItemsMap"] = track_map
    template_json["design"] = design

    return replacements