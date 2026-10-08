from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
from app.services.storage import storage_service
from app.services.media_validator import validate_media
from app.services.media_upload import validate_and_store_media
from app.core.rate_limit import rate_limit
from app.core.settings import settings
from app.core.tenancy import company_id_for_user
from app.core.pagination import PaginationParams, page_result
from app.core.serialization import serialize_mongo, serialize_document
import re
from app.utils.auth import require_roles
from app.db.connection import db

router = APIRouter(prefix="/media-api", tags=["media"])


@router.get("")
async def list_media(
    company_id: str | None = None,
    pagination: PaginationParams = Depends(),
    file_type: str | None = None,
    user=Depends(require_roles("superadmin", "company")),
):
    company_id = await company_id_for_user(user, company_id)
    query = {"company_id": company_id}
    if file_type:
        query["file_type"] = file_type
    if pagination.search:
        query["original_name"] = {"$regex": re.escape(pagination.search), "$options": "i"}
    total = await db.media.count_documents(query)
    sort_field, sort_direction = pagination.sort({"created_at", "updated_at", "original_name", "size"})
    docs = await db.media.find(query).sort(sort_field, sort_direction).skip(pagination.skip).limit(pagination.limit).to_list(pagination.limit)
    docs = [serialize_document(doc) for doc in docs]
    return page_result(serialize_mongo(docs), total, pagination)

# -----------------------------------------------------------
# ObjectId Serializer
# -----------------------------------------------------------
@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    company_id: str = Form(None),
    user=Depends(rate_limit("media-upload", settings.upload_rate_limit))
):
    if user.get("role") not in {"superadmin", "company"}:
        raise HTTPException(403, "Access denied")
    company_id = await company_id_for_user(user, company_id)
    validated, local_path = await validate_and_store_media(file, company_id)

    # 5. Create media document
    media_doc = {
        "company_id": company_id,
        "file_url": local_path,
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

    # 6. Insert
    result = await db.media.insert_one(media_doc)
    media_doc["id"] = str(result.inserted_id)

    # Convert & remove raw ObjectIds (fix crash)
    clean_doc = serialize_mongo(media_doc)

    return {"media": clean_doc}
