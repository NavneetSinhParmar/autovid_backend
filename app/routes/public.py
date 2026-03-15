from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from bson import ObjectId
from app.db.connection import db
from datetime import datetime
from app.utils.auth import require_roles

from app.services.storage import save_upload_file

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
):

    # ---------------------------------------------------
    # 1️⃣ Require company_id for public route
    # ---------------------------------------------------
    if not company_id:
        raise HTTPException(400, "company_id is required")

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
    allowed = ["jpg", "jpeg", "png", "gif", "mp4", "mov", "mp3", "wav"]
    ext = file.filename.split(".")[-1].lower()

    if ext not in allowed:
        raise HTTPException(400, "Unsupported file type")

    # ---------------------------------------------------
    # 4️⃣ Save File
    # ---------------------------------------------------
    local_path, size = await save_upload_file(file, company_id)

    # ---------------------------------------------------
    # 5️⃣ Create media document
    # ---------------------------------------------------
    media_doc = {
        "company_id": company_id,
        "template_id": str(template_oid),
        "file_url": f"./media/{local_path}",
        "file_type": (
            "video" if ext in ["mp4", "mov"]
            else "audio" if ext in ["mp3", "wav"]
            else "image"
        ),
        "original_name": file.filename,
        "size": size,
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

    return {"media": clean_doc}