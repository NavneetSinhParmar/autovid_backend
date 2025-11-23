from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
from app.services.storage import save_upload_file
from app.utils.auth import require_roles
from app.db.connection import db

router = APIRouter(prefix="/media", tags=["media"])

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


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    company_id: str = Form(None),
    user=Depends(require_roles("superadmin", "company"))
):

    # 1. Auto-company resolve for company-role
    if user["role"] == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})

        if not company:
            raise HTTPException(404, "Company record not found for this user")

        company_id = str(company["_id"])

    # 2. superadmin must provide company_id
    if user["role"] == "superadmin" and not company_id:
        raise HTTPException(400, "company_id is required for superadmin")

    # 3. allowed type
    allowed = ["jpg", "jpeg", "png", "gif", "mp4", "mov", "mp3", "wav"]
    ext = file.filename.split(".")[-1].lower()

    if ext not in allowed:
        raise HTTPException(400, "Unsupported file type")

    # 4. Save file
    local_path, size = await save_upload_file(file, company_id)

    # 5. Create media document
    media_doc = {
        "company_id": company_id,
        "file_url": local_path,
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

    # 6. Insert
    result = await db.media.insert_one(media_doc)
    media_doc["id"] = str(result.inserted_id)

    # Convert & remove raw ObjectIds (fix crash)
    clean_doc = serialize_mongo(media_doc)

    return {"media": clean_doc}
