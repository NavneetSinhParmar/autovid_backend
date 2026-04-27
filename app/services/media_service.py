import os
import uuid
from datetime import datetime
from typing import Tuple
from bson import ObjectId
from app.db.connection import db

LOCAL_MEDIA_ROOT = os.getenv("LOCAL_MEDIA_ROOT", "./media")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000/media")

# Ensure root exists
os.makedirs(LOCAL_MEDIA_ROOT, exist_ok=True)


def _save_file(content: bytes, company_id: str, filename: str) -> Tuple[str, int]:
    company_folder = os.path.join(LOCAL_MEDIA_ROOT, company_id)
    os.makedirs(company_folder, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}_{filename}"
    full_path = os.path.join(company_folder, unique_name)

    with open(full_path, "wb") as f:
        f.write(content)

    relative_path = f"{company_id}/{unique_name}"
    return relative_path, len(content)


def _get_file_type(ext: str) -> str:
    if ext in ["mp4", "mov"]:
        return "video"
    elif ext in ["mp3", "wav"]:
        return "audio"
    return "image"


def _serialize(data):
    if isinstance(data, list):
        return [_serialize(i) for i in data]
    if isinstance(data, dict):
        return {k: str(v) if isinstance(v, ObjectId) else _serialize(v) for k, v in data.items()}
    return data


async def save_media_file(content: bytes, filename: str, company_id: str):
    ext = filename.split(".")[-1].lower()

    relative_path, size = _save_file(content, company_id, filename)

    media_doc = {
        "company_id": company_id,
        "file_url": f"{BASE_URL}/{relative_path}",
        "file_type": _get_file_type(ext),
        "original_name": filename,
        "size": size,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await db.media.insert_one(media_doc)
    media_doc["id"] = str(result.inserted_id)

    return _serialize(media_doc)