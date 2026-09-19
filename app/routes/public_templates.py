from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import FileResponse
from bson import ObjectId
from datetime import datetime
from pymongo import ReturnDocument
import asyncio
import shutil

from app.db.connection import db
from app.services.video_renderer import render_preview, render_image_preview, sync_track_item_bounds
from copy import deepcopy
from app.utils.placeholders import replace_placeholders
from app.services.kokoro_tts import synthesize_and_store_media
from app.services.url import build_media_url
from app.services.storage import ensure_media_folder, get_media_abs_path, template_folder_path
from app.services.render_queue import run_render_job

router = APIRouter(prefix="/public/templates", tags=["Public Templates"])


def _template_oid(template_id: str) -> ObjectId:
    if not ObjectId.is_valid(template_id):
        raise HTTPException(status_code=400, detail="Invalid template id")
    return ObjectId(template_id)


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
        "email": company.get("email", ""),
        "description": company.get("description", ""),
        "mobile": company.get("mobile", ""),
        "logo_url": company.get("logo_url", ""),
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

    fields = data.get("fields", {}) or {}
    customer = normalize_customer(data.get("customer", {}) or fields.get("customer", {}) or {})

    company = None
    company_id = template.get("company_id")

    if company_id:
        company = await db.companies.find_one({"_id": ObjectId(company_id)})
        company = await hydrate_company_email(company)

    company = normalize_company(company)

    template_type = str(template.get("type", "video")).lower()

    # IMAGE TEMPLATE
    if template_type in ("img", "image"):

        filename = f"{template_id}_public_preview.jpg"
        preview_path = _template_output_path(template, template_id, filename)

        tpl_json = deepcopy(template.get("template_json", {}))
        fields_snapshot = deepcopy(fields)
        customer_snapshot = deepcopy(customer)
        company_snapshot = deepcopy(company)

        async def work(job_id: str, output_path: str, _folder: str):
            job_tpl_json = deepcopy(tpl_json)
            _apply_fields_to_template(
                job_tpl_json, deepcopy(fields_snapshot), deepcopy(customer_snapshot), deepcopy(company_snapshot)
            )
            await asyncio.to_thread(
                render_image_preview,
                job_tpl_json,
                deepcopy(customer_snapshot),
                deepcopy(company_snapshot),
                output_path
            )
            shutil.copyfile(output_path, preview_path)

        await run_render_job(kind="public_image_preview", extension="jpg", work=work)
        return FileResponse(
            preview_path,
            media_type="image/jpeg",
            filename=filename
        )

    # VIDEO TEMPLATE
    filename = f"{template_id}_public_preview.mp4"
    preview_path = _template_output_path(template, template_id, filename)

    full_template = deepcopy(template)
    fields_snapshot = deepcopy(fields)
    customer_snapshot = deepcopy(customer)
    company_snapshot = deepcopy(company)

    async def work(job_id: str, output_path: str, folder: str):
        job_template = deepcopy(full_template)
        tpl_json = job_template.get("template_json", {}) or {}
        _apply_fields_to_template(tpl_json, deepcopy(fields_snapshot), deepcopy(customer_snapshot), deepcopy(company_snapshot))
        await _apply_dynamic_audio_to_template(
            tpl_json,
            fields=deepcopy(fields_snapshot),
            customer=deepcopy(customer_snapshot),
            company=deepcopy(company_snapshot),
            company_id=str(template.get("company_id") or ""),
            folder_path=folder,
        )
        job_template["template_json"] = tpl_json
        await asyncio.to_thread(
            render_preview,
            job_template,
            {
                "customer": deepcopy(customer_snapshot),
                "company": deepcopy(company_snapshot)
            },
            output_path
        )
        shutil.copyfile(output_path, preview_path)

    # Return the generated file directly so clients receive a usable URL/file
    await run_render_job(kind="public_video_preview", extension="mp4", work=work)
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

    fields = data.get("fields", {}) or {}
    customer = normalize_customer(data.get("customer", {}) or fields.get("customer", {}) or {})

    company = None
    company_id = template.get("company_id")

    if company_id:
        company = await db.companies.find_one({"_id": ObjectId(company_id)})
        company = await hydrate_company_email(company)

    company = normalize_company(company)

    template_type = str(template.get("type", "video")).lower()

    # IMAGE
    if template_type in ("img", "image"):

        filename = f"{template_id}_download.jpg"
        preview_path = _template_output_path(template, template_id, filename)

        tpl_json = deepcopy(template.get("template_json", {}))
        fields_snapshot = deepcopy(fields)
        customer_snapshot = deepcopy(customer)
        company_snapshot = deepcopy(company)

        async def work(job_id: str, output_path: str, _folder: str):
            job_tpl_json = deepcopy(tpl_json)
            _apply_fields_to_template(
                job_tpl_json, deepcopy(fields_snapshot), deepcopy(customer_snapshot), deepcopy(company_snapshot)
            )
            await asyncio.to_thread(
                render_image_preview,
                job_tpl_json,
                deepcopy(customer_snapshot),
                deepcopy(company_snapshot),
                output_path
            )
            shutil.copyfile(output_path, preview_path)

        await run_render_job(kind="public_image_download", extension="jpg", work=work)
        return FileResponse(
            preview_path,
            media_type="image/jpeg",
            filename=filename
        )

    # VIDEO
    filename = f"{template_id}_download.mp4"
    preview_path = _template_output_path(template, template_id, filename)

    full_template = deepcopy(template)
    fields_snapshot = deepcopy(fields)
    customer_snapshot = deepcopy(customer)
    company_snapshot = deepcopy(company)

    async def work(job_id: str, output_path: str, folder: str):
        job_template = deepcopy(full_template)
        tpl_json = job_template.get("template_json", {}) or {}
        _apply_fields_to_template(tpl_json, deepcopy(fields_snapshot), deepcopy(customer_snapshot), deepcopy(company_snapshot))
        await _apply_dynamic_audio_to_template(
            tpl_json,
            fields=deepcopy(fields_snapshot),
            customer=deepcopy(customer_snapshot),
            company=deepcopy(company_snapshot),
            company_id=str(template.get("company_id") or ""),
            folder_path=folder,
        )
        job_template["template_json"] = tpl_json
        await asyncio.to_thread(
            render_preview,
            job_template,
            {
                "customer": deepcopy(customer_snapshot),
                "company": deepcopy(company_snapshot)
            },
            output_path
        )
        shutil.copyfile(output_path, preview_path)

    await run_render_job(kind="public_video_download", extension="mp4", work=work)
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

    exact = _ci_get(fields, path)
    if exact is not None:
        return exact

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
                if value is None and fp.startswith("customer.") and isinstance(customer, dict):
                    value = _get_field_value(customer, fp.split(".", 1)[1])
                if value is None and fp.startswith("company.") and isinstance(company, dict):
                    value = _get_field_value(company, fp.split(".", 1)[1])

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
    sync_track_item_bounds(design)
    template_json["design"] = design

    return replacements


async def _apply_dynamic_audio_to_template(
    template_json: dict,
    *,
    fields: dict,
    customer: dict,
    company: dict,
    company_id: str | None,
    folder_path: str | None = None,
):
    """
    For audio items marked as customer fields (dataType=audio), resolve `voisetext`
    placeholders like `{customer.full_name}` / `{custom_text1}` and generate a TTS file.
    Then set `details.src` to the generated file so `render_preview()` includes it.
    """
    if not isinstance(template_json, dict):
        return

    if not company_id:
        return

    design = template_json.get("design", {})
    track_map = design.get("trackItemsMap", {})

    context = {
        "customer": customer or {},
        "company": company or {},
        **(fields or {}),
    }

    for _tid, item in (track_map or {}).items():
        if not isinstance(item, dict):
            continue
        if item.get("type") != "audio":
            continue

        metadata = item.get("metadata", {}) or {}
        if not metadata.get("isCustomerField"):
            continue
        if str(metadata.get("dataType") or metadata.get("datatype") or "").lower() != "audio":
            continue

        voisetext = (
            item.get("voisetext")
            or item.get("voiceText")
            or (item.get("details", {}) or {}).get("voisetext")
        )
        if not isinstance(voisetext, str) or not voisetext.strip():
            continue

        resolved_text = replace_placeholders(voisetext, context).strip()
        if not resolved_text:
            continue

        voice = item.get("voice") or metadata.get("voice") or "af_heart"
        speed = item.get("playbackRate") or item.get("speed") or 1.0
        try:
            speed = float(speed)
        except Exception:
            speed = 1.0

        stored = await synthesize_and_store_media(
            company_id=str(company_id),
            voisetext=resolved_text,
            voice=str(voice),
            speed=speed,
            folder_path=folder_path,
        )

        details = item.get("details", {}) or {}
        details["src"] = f"./media/{stored['file_url']}"
        item["details"] = details
        item["voisetext"] = resolved_text

        # Also update metadata urls so clients can read the new mp3
        meta = item.get("metadata", {}) or {}
        new_public_url = build_media_url(stored["file_url"])
        if new_public_url:
            meta["uploadedUrl"] = new_public_url
            meta["originalUrl"] = new_public_url
        item["metadata"] = meta

    design["trackItemsMap"] = track_map
    template_json["design"] = design
