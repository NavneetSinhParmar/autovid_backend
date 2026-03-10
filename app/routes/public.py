from fastapi import APIRouter, HTTPException
from bson import ObjectId
from app.db.connection import db

router = APIRouter(prefix="/api/public", tags=["public"])


def _serialize_template(t: dict) -> dict:
    return {
        "id": str(t.get("_id")) if t.get("_id") is not None else None,
        "template_name": t.get("template_name"),
        "category": t.get("category"),
        "type": t.get("type"),
        "duration": t.get("duration"),
        "preview_image_url": t.get("preview_image_url"),
        "base_video_url": t.get("base_video_url"),
        "base_image_url": t.get("base_image_url"),
        "base_audio_url": t.get("base_audio_url"),
        "template_json": t.get("template_json"),
    }


def _serialize_media(m: dict) -> dict:
    return {
        "id": str(m.get("_id")) if m.get("_id") is not None else None,
        "file_url": m.get("file_url"),
        "file_type": m.get("file_type"),
        "original_name": m.get("original_name"),
        "size": m.get("size"),
    }


@router.get("/templates")
async def list_public_templates():
    """List all published and active templates (no authentication)."""
    templates = await db.templates.find({"status": "active", "public": True}).to_list(length=1000)
    safe = [_serialize_template(t) for t in templates]
    return {"templates": safe}


@router.get("/template/{template_id}")
async def get_public_template(template_id: str):
    """Return a single published template by id (no authentication)."""
    try:
        oid = ObjectId(template_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid template id")

    template = await db.templates.find_one({"_id": oid, "status": "active", "public": True})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return {"template": _serialize_template(template)}


@router.get("/media/templates/{template_id}")
async def get_media_for_template(template_id: str):
    """Return media assets referenced by the public template's base URLs."""
    try:
        oid = ObjectId(template_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid template id")

    template = await db.templates.find_one({"_id": oid, "status": "active", "public": True})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    file_urls = []
    for key in ("base_video_url", "base_image_url", "base_audio_url"):
        val = template.get(key)
        if val:
            file_urls.append(val)

    media_docs = []
    if file_urls:
        media_docs = await db.media.find({"file_url": {"$in": file_urls}}).to_list(length=100)

    safe_media = [_serialize_media(m) for m in media_docs]
    return {"media": safe_media}
