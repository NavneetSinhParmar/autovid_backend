import os
import uuid
from typing import Tuple

LOCAL_MEDIA_ROOT = os.getenv("LOCAL_MEDIA_ROOT", "./media")

def save_file_local(file_obj, company_id: str, filename: str) -> str:
    os.makedirs(os.path.join(LOCAL_MEDIA_ROOT, company_id), exist_ok=True)
    unique = f"{uuid.uuid4().hex}_{filename}"
    path = os.path.join(LOCAL_MEDIA_ROOT, company_id, unique)
    with open(path, "wb") as f:
        f.write(file_obj)
        return path

async def save_upload_file(file, company_id: str) -> Tuple[str, int]:
    content = await file.read()
    path = save_file_local(content, company_id, file.filename)
    return path, len(content)
