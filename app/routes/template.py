import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query
from fastapi.responses import FileResponse
from datetime import datetime
from bson import ObjectId
import json
import asyncio
import shutil
from copy import deepcopy
from app.db.connection import db
from app.utils.auth import require_roles,get_current_user
from app.services.video_renderer import render_preview, render_image_preview, sync_track_item_bounds
from app.utils.placeholders import replace_placeholders
from app.services.kokoro_tts import synthesize_and_store_media
from app.services.url import build_media_url
from app.services.storage import (
    delete_media_folder,
    ensure_media_folder,
    get_media_abs_path,
    template_folder_path,
)
from app.services.render_queue import enqueue_celery_render_job
from app.core.tenancy import company_id_for_user, owned_customer, owned_template
from app.core.rate_limit import rate_limit
from app.core.settings import settings
from app.core.pagination import PaginationParams, page_result
from app.models.template_model import TemplateCreate, TemplateUpdate
from app.core.serialization import serialize_document
import uuid
import os
import logging
router = APIRouter(prefix="/templates", tags=["Templates"])
logger = logging.getLogger(__name__)


def _template_folder(template: dict, template_id: str) -> str:
    folder = template.get("folder_path")
    if not folder:
        company_id = template.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="Template company_id missing")
        folder = template_folder_path(str(company_id), template_id)
    return ensure_media_folder(folder)


def _template_output_path(template: dict, template_id: str, filename: str) -> str:
    return get_media_abs_path(f"{_template_folder(template, template_id)}/{filename}")

# ================= CREATE TEMPLATE =================
@router.post("/")
async def create_template(
    data: TemplateCreate,
    user=Depends(require_roles("company"))
):

    company = await db.companies.find_one({
        "user_id": str(user["_id"])
    })

    if not company:
        raise HTTPException(400, "Company not found")

    values = data.model_dump()
    template_json = values.get("template_json", {})
    design = template_json.get("design", {}) if isinstance(template_json, dict) else {}
    options = template_json.get("options", {}) if isinstance(template_json, dict) else {}
    if isinstance(design, dict):
        if "fps" not in design and isinstance(options, dict) and "fps" in options:
            design["fps"] = options["fps"]
        if "size" not in design:
            design["size"] = {"width": 1920, "height": 1080}
        sync_track_item_bounds(design)
        template_json["design"] = design

    template_doc = {
        "company_id": str(company["_id"]),
        "template_name": values["template_name"],
        "category": values.get("category", "general"),
        "preview_image_url": values.get("preview_image_url"),
        "base_video_url": values.get("base_video_url"),
        "base_image_url": values.get("base_image_url"),
        "base_audio_url": values.get("base_audio_url"),
        "duration": values.get("duration"),
        "trim": values.get("trim"),
        "template_json": template_json,
        "type": values.get("type", "video"),
        "public": values.get("public", False),
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await db.templates.insert_one(template_doc)
    template_id = str(result.inserted_id)
    folder_path = ensure_media_folder(template_folder_path(str(company["_id"]), template_id))
    await db.templates.update_one(
        {"_id": result.inserted_id},
        {"$set": {"folder_path": folder_path}}
    )

    return {
        "message": "Template created successfully",
        "template_id": template_id,
        "folder_path": folder_path
    }

# ================= LIST TEMPLATES =================
@router.get("/")
async def list_templates(
    pagination: PaginationParams = Depends(),
    category: str | None = None,
    template_type: str | None = None,
    status: str = "active",
    user=Depends(require_roles("company")),
):

    company = await db.companies.find_one({
        "user_id": str(user["_id"])
    })

    query = {
        "company_id": str(company["_id"]),
        "status": status,
    }
    if category:
        query["category"] = category
    if template_type:
        query["type"] = template_type
    if pagination.search:
        query["template_name"] = {"$regex": re.escape(pagination.search), "$options": "i"}
    total = await db.templates.count_documents(query)
    sort_field, sort_direction = pagination.sort({"created_at", "updated_at", "template_name", "category"})
    templates = await db.templates.find(query).sort(sort_field, sort_direction).skip(pagination.skip).limit(pagination.limit).to_list(pagination.limit)

    for t in templates:
        t["id"] = str(t["_id"])
        del t["_id"]

    result = page_result(templates, total, pagination)
    result["templates"] = result.pop("items")
    return result

# ================= GET TEMPLATE =================
@router.get("/{template_id}")
async def get_template(template_id: str, user=Depends(require_roles("company"))):
    company_id = await company_id_for_user(user)
    template = await owned_template(template_id, company_id)

    template["id"] = str(template["_id"])
    del template["_id"]

    return {"template": template}

# ================= UPDATE TEMPLATE (PATCH) =================
@router.patch("/{template_id}")
async def update_template(
    template_id: str,
    data: TemplateUpdate,
    user=Depends(require_roles("company"))
):
    company_id = await company_id_for_user(user)
    await owned_template(template_id, company_id)
    update_values = data.model_dump(exclude_none=True)
    if not update_values:
        raise HTTPException(400, "No fields provided for update")
    await db.templates.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {**update_values, "updated_at": datetime.utcnow()}}
    )

    return {"message": "Template updated successfully"}

# ================= DELETE TEMPLATE =================
@router.delete("/{template_id}")
async def delete_template(template_id: str, user=Depends(require_roles("company"))):
    company_id = await company_id_for_user(user)
    template = await owned_template(template_id, company_id)

    await db.templates.delete_one({"_id": ObjectId(template_id)})
    await db.media.delete_many({"template_id": template_id})
    await db.video_tasks.delete_many({
        "$or": [
            {"template_id": template_id},
            {"template_id": ObjectId(template_id)},
        ]
    })
    delete_media_folder(_template_folder(template, template_id))

    return {"message": "Template deleted"}

# ================= PREVIEW TEMPLATE =================
@router.post("/{template_id}/preview", status_code=202)
async def preview_template(
    template_id: str,
    user=Depends(rate_limit("render-preview", settings.render_rate_limit)),
):
    if user.get("role") != "company":
        raise HTTPException(403, "Company access required")
    company_id = await company_id_for_user(user)
    template = await owned_template(template_id, company_id)

    company_data = await db.companies.find_one({"_id": ObjectId(company_id)})
    company_data = await hydrate_company_email(company_data)
    company_context = normalize_company(company_data)
    is_image = str(template.get("type", "video")).lower() in ("img", "image")
    job = await enqueue_celery_render_job(
        kind="image_preview" if is_image else "video_preview",
        extension="jpg" if is_image else "mp4",
        company_id=company_id,
        template_id=template_id,
        payload={"template": template, "context": {"customer": {}, "company": company_context}},
    )
    return {"message": "Preview queued", **job}

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
        "email": company.get("email", ""),
        "description": company.get("description", ""),        
        "mobile": company.get("mobile", ""),        
        "logo_url": company.get("logo_url", ""),   # image path / url
    }

async def hydrate_company_email(company: dict | None) -> dict | None:
    if not company or company.get("email"):
        return company

    user_id = company.get("user_id")
    if not user_id:
        return company

    try:
        user_doc = await db.users.find_one({"_id": ObjectId(str(user_id))}, {"email": 1})
    except Exception:
        user_doc = await db.users.find_one({"_id": str(user_id)}, {"email": 1})

    if user_doc and user_doc.get("email"):
        company["email"] = user_doc["email"]
    return company

PLACEHOLDER_RE = re.compile(r"\{\{?\s*([\w.]+)\s*\}?\}")

def _resolve_placeholders(text: str, context: dict) -> str:
    """
    Replace {{customer.full_name}}, {{company.company_name}}, {{customer.city}}
    and also flat {{full_name}} style placeholders.

    context = {
        "customer": {"full_name": "John", "city": "Mumbai", ...},
        "company":  {"company_name": "Acme", "mobile": "...", ...},
    }
    """
    def replacer(match):
        path = match.group(1).strip()          # e.g. "customer.full_name"
        parts = path.split(".")

        if len(parts) == 1:
            # flat key → search all context buckets
            key = parts[0].lower()
            for bucket in context.values():
                if isinstance(bucket, dict):
                    # case-insensitive key lookup
                    for k, v in bucket.items():
                        if k.lower() == key:
                            return str(v) if v is not None else ""
            return match.group(0)              # leave untouched if not found

        # nested: parts[0] = bucket, rest = key path
        bucket_name = parts[0].lower()
        bucket = None
        for k, v in context.items():
            if k.lower() == bucket_name:
                bucket = v
                break
        if not isinstance(bucket, dict):
            return match.group(0)

        value = bucket
        for key in parts[1:]:
            if not isinstance(value, dict):
                return match.group(0)
            # case-insensitive
            value = next(
                (v for k, v in value.items() if k.lower() == key.lower()),
                None
            )
            if value is None:
                return ""
        return str(value) if value is not None else ""

    return PLACEHOLDER_RE.sub(replacer, text)

async def _apply_dynamic_audio_to_template(
    template_json: dict,
    *,
    customer: dict,
    company: dict,
    company_id: str | None,
    folder_path: str | None = None,
):
    """
    For every audio track item where:
        metadata.isCustomerField == True
        metadata.fieldPath       == "voiceover"   (case-insensitive)
        metadata.dataType        == "audio"        (case-insensitive)

    1. Resolve placeholders in item["voisetext"]  → resolved_text
    2. Call synthesize_and_store_media(resolved_text, voice, speed)
    3. Patch item.details.src + metadata.uploadedUrl / originalUrl
    """
    if not isinstance(template_json, dict) or not company_id:
        return

    design    = template_json.get("design", {})
    track_map = design.get("trackItemsMap", {})

    context = {
        "customer": customer or {},
        "company":  company  or {},
    }

    for tid, item in (track_map or {}).items():
        if not isinstance(item, dict):
            continue
        if item.get("type") != "audio":
            continue

        metadata = item.get("metadata") or {}

        # ── Guard checks ──────────────────────────────────────────────────
        if not metadata.get("isCustomerField"):
            continue

        field_path = str(
            metadata.get("fieldPath") or metadata.get("fieldpath") or ""
        ).strip().lower()
        if field_path != "voiceover":
            continue

        data_type = str(
            metadata.get("dataType") or metadata.get("datatype") or ""
        ).strip().lower()
        if data_type != "audio":
            continue

        # ── Resolve voisetext ─────────────────────────────────────────────
        raw_text = (
            item.get("voisetext")
            or (item.get("details") or {}).get("voisetext")
            or ""
        )
        if not isinstance(raw_text, str) or not raw_text.strip():
            logger.debug("Skipping TTS track with empty text")
            continue

        resolved_text = _resolve_placeholders(raw_text, context).strip()
        if not resolved_text:
            logger.debug("Skipping TTS track after empty placeholder resolution")
            continue


        # ── Voice / speed ─────────────────────────────────────────────────
        voice = (
            item.get("voice")
            or metadata.get("voice")
            or "af_heart"
        )
        try:
            speed = float(item.get("playbackRate") or item.get("speed") or 1.0)
        except (TypeError, ValueError):
            speed = 1.0
        speed = max(0.5, min(2.0, speed))      # clamp to valid range

        # ── Generate TTS via synthesize_and_store_media ───────────────────
        try:
            stored = await synthesize_and_store_media(
                company_id=str(company_id),
                voisetext=resolved_text,
                voice=str(voice),
                speed=speed,
                folder_path=folder_path,
            )
        except Exception as exc:
            logger.exception("TTS generation failed for template track")
            continue          # leave original audio untouched rather than crashing

        # ── Patch the item in-place ───────────────────────────────────────
        # details.src  →  local file path used by the renderer
        details = item.get("details") or {}
        details["src"] = f"./media/{stored['file_url']}"
        item["details"] = details

        # keep resolved text so renderer doesn't have to resolve again
        item["voisetext"] = resolved_text

        # public URL stored in metadata for logging / frontend display
        new_url = build_media_url(stored["file_url"])
        if new_url:
            metadata["uploadedUrl"]  = new_url
            metadata["originalUrl"]  = new_url
        item["metadata"] = metadata


    # write back (mutates template_json in-place, caller already holds ref)
    design["trackItemsMap"] = track_map
    sync_track_item_bounds(design)
    template_json["design"] = design

@router.post("/{template_id}/preview/{customer_id}", status_code=202)
async def preview_template_customer(
    template_id: str,
    customer_id: str,
    user=Depends(rate_limit("render-customer-preview", settings.render_rate_limit)),
):
    if user.get("role") != "company":
        raise HTTPException(403, "Company access required")
    company_id = await company_id_for_user(user)
    template = await owned_template(template_id, company_id)
    customer = await owned_customer(customer_id, company_id)

    customer = normalize_customer(customer)
    company_doc = await db.companies.find_one({"_id": ObjectId(company_id)})
    company_doc = await hydrate_company_email(company_doc)
    company_context = normalize_company(company_doc)
    is_image = str(template.get("type", "video")).lower() in ("img", "image")
    job = await enqueue_celery_render_job(
        kind="customer_image_preview" if is_image else "customer_video_preview",
        extension="jpg" if is_image else "mp4",
        company_id=company_id,
        customer_id=customer_id,
        template_id=template_id,
        payload={
            "template": template,
            "context": {"customer": customer, "company": company_context},
            "dynamic_tts": not is_image,
        },
    )
    return {"message": "Preview queued", **job}

@router.get("/{template_id}/download/{customer_id}")
async def download_video(
    template_id: str,
    customer_id: str,
    user=Depends(require_roles("company")),
):
    company_id = await company_id_for_user(user)
    template = await owned_template(template_id, company_id)
    await owned_customer(customer_id, company_id)

    template_type = str(template.get("type", "video")).lower()
    is_image = template_type in ("img", "image")
    ext = "jpg" if is_image else "mp4"
    media_type = "image/jpeg" if is_image else "video/mp4"

    filename = f"{template_id}_{customer_id}_preview.{ext}"
    file_path = _template_output_path(template, template_id, filename)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Video file does not exist. You must first generate a preview."
        )

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename
    )
