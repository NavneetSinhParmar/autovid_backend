import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from datetime import datetime
from bson import ObjectId
import json
from app.db.connection import db
from app.utils.auth import require_roles,get_current_user
from app.services.video_renderer import render_preview,render_image_preview
from app.utils.placeholders import replace_placeholders
from app.services.kokoro_tts import synthesize_and_store_media
from app.services.url import build_media_url
import uuid
import os
router = APIRouter(prefix="/templates", tags=["Templates"])

# ================= CREATE TEMPLATE =================
@router.post("/")
async def create_template(
    data: dict,
    user=Depends(require_roles("company"))
):

    company = await db.companies.find_one({
        "user_id": str(user["_id"])
    })

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
        "preview_image_url": data.get("preview_image_url"),
        "base_video_url": data.get("base_video_url"),
        "base_image_url": data.get("base_image_url"),
        "base_audio_url": data.get("base_audio_url"),
        "duration": data.get("duration"),
        "trim": data.get("trim"),
        "template_json": template_json,
        "type": data.get("type", "video"),
        "public": data.get("public", True),
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


@router.get("/")
async def get_template(
    template_name: str = Query(None),
    category: str = Query(None),
    type: str = Query(None),
    current_user: dict = Depends(get_current_user)
):

    query = {
        "status": "active",
        "company_id": current_user["company_id"]
    }

    if template_name:
        query["template_name"] = template_name

    if category:
        query["category"] = category

    if type:
        query["type"] = type

    template = await db.templates.find_one(query)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template["id"] = str(template["_id"])
    del template["_id"]

    return {"template": template}

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

    company_id = template.get("company_id")
    company_data = None
    if company_id:
        company_data = await db.companies.find_one({"_id": ObjectId(company_id)})

    media_dir = os.path.abspath("media")
    os.makedirs(media_dir, exist_ok=True)
    template_type = str(template.get("type", "video")).lower()

    try:
        company_context = {}
        if company_data:
            company_context = {
                "company_name": company_data.get("company_name") or company_data.get("name") or "",
                "logo_url": company_data.get("logo_url") or company_data.get("logoUrl") or company_data.get("logo") or "",
                "description": company_data.get("description") or "",
                "mobile": company_data.get("mobile") or "",
                "email": company_data.get("email") or "",
            }

        # IMAGE template -> JPEG
        if template_type in ("img", "image"):
            preview_filename = f"{template_id}_preview.jpg"
            preview_path = os.path.join(media_dir, preview_filename)
            await run_in_threadpool(
                render_image_preview,
                template["template_json"],
                {},
                company_context,
                preview_path,
            )
            return FileResponse(path=preview_path, media_type="image/jpeg", filename=preview_filename)

        # VIDEO template -> MP4
        preview_filename = f"{template_id}_preview.mp4"
        preview_path = os.path.join(media_dir, preview_filename)
        await run_in_threadpool(
            render_preview,
            template,
            {"customer": {}, "company": company_context},
            preview_path,
        )
        return FileResponse(path=preview_path, media_type="video/mp4", filename=preview_filename)
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
            print(f"[TTS] Skipping track {tid}: empty voisetext")
            continue

        resolved_text = _resolve_placeholders(raw_text, context).strip()
        if not resolved_text:
            print(f"[TTS] Skipping track {tid}: resolved text is empty")
            continue

        print(f"[TTS] Track {tid} | raw: {raw_text!r} → resolved: {resolved_text!r}")

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
            )
        except Exception as exc:
            print(f"[TTS] ERROR generating audio for track {tid}: {exc}")
            import traceback; traceback.print_exc()
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

        print(f"[TTS] Track {tid} patched → {details['src']}")

    # write back (mutates template_json in-place, caller already holds ref)
    design["trackItemsMap"] = track_map
    template_json["design"] = design

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

    template_type = str(template.get("type", "video")).lower()

    # 🔀 IMAGE (img/image) -> JPEG
    if template_type in ("img", "image"):
        preview_filename = f"{template_id}_{customer_id}_preview.jpg"
        preview_path = os.path.join(media_dir, preview_filename)

        await run_in_threadpool(
            render_image_preview,
            template["template_json"],
            customer,
            company,
            preview_path
        )

        return FileResponse(preview_path, media_type="image/jpeg", filename=preview_filename)

    # 🎥 VIDEO
    preview_filename = f"{template_id}_{customer_id}_preview.mp4"
    preview_path = os.path.join(media_dir, preview_filename)

    # ✅ Dynamic audio TTS (voisetext -> mp3) before rendering
    tpl_json = template.get("template_json", {}) or {}
    effective_company_id = template.get("company_id") or customer.get("linked_company_id")
    await _apply_dynamic_audio_to_template(
        tpl_json,
        customer=customer,
        company=company,
        company_id=str(effective_company_id or ""),
    )
    template["template_json"] = tpl_json

    await run_in_threadpool(
        render_preview,
        template,
        {
            "customer": customer,
            "company": company
        },
        preview_path
    )

    return FileResponse(preview_path, media_type="video/mp4")

@router.get("/{template_id}/download/{customer_id}")
async def download_video(template_id: str, customer_id: str):

    template = await db.templates.find_one({"_id": ObjectId(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template_type = str(template.get("type", "video")).lower()
    is_image = template_type in ("img", "image")
    ext = "jpg" if is_image else "mp4"
    media_type = "image/jpeg" if is_image else "video/mp4"

    filename = f"{template_id}_{customer_id}_preview.{ext}"
    file_path = os.path.abspath(os.path.join("media", filename))

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