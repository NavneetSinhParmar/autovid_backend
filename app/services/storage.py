import os
import uuid
from typing import Tuple

LOCAL_MEDIA_ROOT = os.getenv("LOCAL_MEDIA_ROOT", "./media")

def save_file_local(file_obj: bytes, company_id: str, filename: str) -> str:
    # Ensure company folder exists
    company_folder = os.path.join(LOCAL_MEDIA_ROOT, company_id)
    os.makedirs(company_folder, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}_{filename}"

    # Full filesystem path (OS dependent, internal use only)
    full_path = os.path.join(company_folder, unique_name)

    with open(full_path, "wb") as f:
        f.write(file_obj)

    # 🔥 Return RELATIVE path WITHOUT "media/" prefix
    # url.py will add the /media/ prefix when building full URLs
    # This prevents duplicate paths like /media/./media/...
    # return f"{company_id}/{unique_name}"
    return f"{full_path}"


async def save_upload_file(file, company_id: str) -> Tuple[str, int]:
    content = await file.read()
    path = save_file_local(content, company_id, file.filename)
    return path, len(content)
