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
    # fields: simple key->value mapping used to replace text items
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

        # Apply field replacements into a copy of template_json
        tpl_json = deepcopy(template.get("template_json", {}))
        replacements = _apply_fields_to_template(tpl_json, fields, customer, company)
        print(f"Public preview replacements: {replacements}")
        print("Applied fields to template JSON for image preview: ", tpl_json)  
        
        await run_in_threadpool(
            render_image_preview,
            tpl_json,
            customer,
            company,
            preview_path
        )

        # If caller requested download explicitly, stream the file. Otherwise return JSON with updated template
        if data.get("download"):
            return FileResponse(
                preview_path,
                media_type="image/jpeg",
                filename=filename
            )
        return {
            "preview_path": preview_path,
            "filename": filename,
            "template_json": tpl_json,
        }

    # VIDEO TEMPLATE
    filename = f"{template_id}_public_preview.mp4"
    preview_path = os.path.join(media_dir, filename)

    # VIDEO TEMPLATE: apply fields to a copy of the template and render
    full_template = deepcopy(template)
    tpl_json = full_template.get("template_json", {}) or {}
    replacements = _apply_fields_to_template(tpl_json, fields, customer, company)
    print(f"Public preview replacements: {replacements}")
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

    if data.get("download"):
        return FileResponse(
            preview_path,
            media_type="video/mp4",
            filename=filename
        )
    return {
        "preview_path": preview_path,
        "filename": filename,
        "template_json": tpl_json,
        "replacements": replacements,
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


def _apply_fields_to_template(template_json: dict, fields: dict, customer: dict | None = None, company: dict | None = None):
    if not isinstance(template_json, dict):
        return
    design = template_json.get("design") if isinstance(template_json.get("design"), dict) else {}
    track_map = design.get("trackItemsMap") if isinstance(design.get("trackItemsMap"), dict) else {}

    replacements = []
    for tid, item in list(track_map.items()):
        try:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            metadata = item.get("metadata") or {}
            is_customer_field = metadata.get("isCustomerField")
            # Accept truthy values and strings like "true"
            if isinstance(is_customer_field, str):
                is_customer_field = is_customer_field.lower() in ("1", "true", "yes")
            if not is_customer_field:
                continue
            field_path = metadata.get("fieldPath") or metadata.get("fieldpath")
            if not field_path:
                continue
            # Normalize field_path like '{{customer.name}}' -> 'customer.name'
            fp = str(field_path).strip()
            if fp.startswith("{{") and fp.endswith("}}"):
                fp = fp[2:-2].strip()

            value = _get_field_value(fields, fp)
            # fallback: if not found in fields, try customer/company dicts
            if value is None and isinstance(customer, dict):
                # if fp starts with 'customer.' use that path
                if fp.startswith("customer."):
                    subpath = fp.split('.', 1)[1]
                    value = _get_field_value(customer, subpath)
                else:
                    # try direct key lookup in customer (case-insensitive)
                    for k, v in customer.items():
                        if str(k).lower() == str(fp).lower():
                            value = v
                            break
            if value is None and isinstance(company, dict):
                if fp.startswith("company."):
                    subpath = fp.split('.', 1)[1]
                    value = _get_field_value(company, subpath)
                else:
                    for k, v in company.items():
                        if str(k).lower() == str(fp).lower():
                            value = v
                            break
            if value is None:
                # no matching key in request fields
                continue
            # set value as string into details.text
            details = item.get("details") or {}
            old = details.get("text")
            details["text"] = str(value)
            # put back
            item["details"] = details
            track_map[tid] = item
            try:
                replacements.append({"id": tid, "old": old, "new": str(value)})
            except Exception:
                replacements.append({"id": tid, "old": old, "new": None})
        except Exception:
            continue
    # assign back
    if design:
        design["trackItemsMap"] = track_map
        template_json["design"] = design
    return replacements