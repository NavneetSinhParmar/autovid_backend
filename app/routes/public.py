from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from bson import ObjectId
from app.db.connection import db
from datetime import datetime
from app.utils.auth import require_roles

from app.services.storage import storage_service, template_folder_path
from app.services.url import build_media_url
from app.services.media_validator import validate_media
from app.services.media_upload import validate_and_store_media
from app.core.rate_limit import rate_limit
from app.core.settings import settings
from app.core.tenancy import company_id_for_user

router = APIRouter(prefix="/api/public", tags=["public"])


def _serialize_template(t: dict) -> dict:
    return {
        "id": str(t.get("_id")) if t.get("_id") is not None else None,
        "template_name": t.get("template_name"),
        "category": t.get("category"),
        "type": t.get("type"),
        "duration": t.get("duration"),
        "preview_image_url": build_media_url(t.get("preview_image_url")),
        "base_video_url": build_media_url(t.get("base_video_url")),
        "base_image_url": build_media_url(t.get("base_image_url")),
        "base_audio_url": build_media_url(t.get("base_audio_url")),
        "template_json": t.get("template_json"),
    }


def _serialize_media(m: dict) -> dict:
    return {
        "id": str(m.get("_id")) if m.get("_id") is not None else None,
        "file_url": build_media_url(m.get("file_url")),
        "file_type": m.get("file_type"),
        "original_name": m.get("original_name"),
        "size": m.get("size"),
    }


@router.get("/templates")
async def list_public_templates(page: int = 1, limit: int = 50):
    """List all published and active templates (no authentication)."""
    page = max(1, page)
    limit = min(100, max(1, limit))
    query = {"status": "active", "public": True}
    total = await db.templates.count_documents(query)
    templates = await db.templates.find(query).sort("created_at", -1).skip((page - 1) * limit).limit(limit).to_list(limit)
    safe = [_serialize_template(t) for t in templates]
    return {"templates": safe, "page": page, "limit": limit, "total": total, "has_next": page * limit < total}


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


# -----------------------------------------------------------
# ObjectId Serializer
# -----------------------------------------------------------
def serialize_mongo(data):
    if isinstance(data, list):
        return [serialize_mongo(i) for i in data]

    if isinstance(data, dict):
        new_data = {}
        for k, v in data.items():
            if isinstance(v, ObjectId):
                new_data[k] = str(v)
            else:
                new_data[k] = serialize_mongo(v)
        return new_data

    return data

@router.post("/media/templates")
async def upload_media_for_template(
    template_id: str = Form(...),
    file: UploadFile = File(...),
    company_id: str = Form(None),
    user=Depends(rate_limit("template-upload", settings.upload_rate_limit)),
):

    # ---------------------------------------------------
    # 1️⃣ Require company_id for public route
    # ---------------------------------------------------
    if user.get("role") not in {"superadmin", "company"}:
        raise HTTPException(403, "Access denied")
    company_id = await company_id_for_user(user, company_id)

    # ---------------------------------------------------
    # 2️⃣ Validate Template
    # ---------------------------------------------------
    try:
        template_oid = ObjectId(template_id)
    except:
        raise HTTPException(400, "Invalid template id")

    template = await db.templates.find_one({
        "_id": template_oid,
        "company_id": company_id
    })

    if not template:
        raise HTTPException(404, "Template not found")

    # ---------------------------------------------------
    # 3️⃣ File validation
    # ---------------------------------------------------
    validated, local_path = await validate_and_store_media(file, template_folder_path(company_id, template_id))

    if not validated:
        raise HTTPException(400, "Invalid media")

    # ---------------------------------------------------
    # 4️⃣ Save File
    # ---------------------------------------------------

    # ---------------------------------------------------
    # 5️⃣ Create media document
    # ---------------------------------------------------
    media_doc = {
        "company_id": company_id,
        "template_id": str(template_oid),
        "file_url": f"./media/{local_path}",
        "file_type": validated.kind,
        "original_name": file.filename,
        "size": validated.size,
        "metadata": {
            "duration": validated.duration,
            "width": validated.width,
            "height": validated.height,
            "codec": validated.codec,
        },
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await db.media.insert_one(media_doc)
    media_doc["id"] = str(result.inserted_id)

    # ---------------------------------------------------
    # 6️⃣ Update Template Base Media
    # ---------------------------------------------------
    update_data = {}

    if media_doc["file_type"] == "image":
        update_data["base_image_url"] = local_path

    elif media_doc["file_type"] == "video":
        update_data["base_video_url"] = local_path

    elif media_doc["file_type"] == "audio":
        update_data["base_audio_url"] = local_path

    if update_data:
        await db.templates.update_one(
            {"_id": template_oid},
            {"$set": update_data}
        )

    # ---------------------------------------------------
    # 7️⃣ Serialize Mongo ObjectId
    # ---------------------------------------------------
    clean_doc = serialize_mongo(media_doc)
    clean_doc["file_url"] = build_media_url(clean_doc.get("file_url"))

    return {"media": clean_doc}
