import os
import uuid
from typing import Tuple

LOCAL_MEDIA_ROOT = os.getenv("LOCAL_MEDIA_ROOT", "./media")

def save_file_local(file_obj: bytes, folder_path: str, filename: str) -> str:
    company_folder = os.path.join(LOCAL_MEDIA_ROOT, folder_path)
    os.makedirs(company_folder, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}_{filename}"
    full_path = os.path.join(company_folder, unique_name)

    with open(full_path, "wb") as f:
        f.write(file_obj)

    return f"{folder_path}/{unique_name}"

async def save_company_file(file, company_user_id: str):
    content = await file.read()
    path = save_file_local(content, company_user_id, file.filename)
    return path, len(content)


async def save_customer_file(
    file,
    company_user_id: str,
    customer_id: str
):
    content = await file.read()
    folder = f"{company_user_id}/customers/{customer_id}"
    path = save_file_local(content, folder, file.filename)
    return path, len(content)


def save_file_local_for_media(file_obj: bytes, company_id: str, filename: str) -> str:
    print(f"Saving file for company {company_id} with filename {filename}")
    # Ensure company folder exists
    company_folder = os.path.join(LOCAL_MEDIA_ROOT, company_id)
    os.makedirs(company_folder, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}_{filename}"

    # Full filesystem path (OS dependent, internal use only)
    full_path = os.path.join(company_folder, unique_name)
    print("Saving file to:", full_path)
    with open(full_path, "wb") as f:
        f.write(file_obj)

    # 🔥 Return RELATIVE path WITHOUT "media/" prefix
    # url.py will add the /media/ prefix when building full URLs
    # This prevents duplicate paths like /media/./media/...
    return f"{company_id}/{unique_name}"


async def save_upload_file(file, company_id: str) -> Tuple[str, int]:
    print("Saving uploaded file for company:", company_id)
    content = await file.read()
    path = save_file_local_for_media(content, company_id, file.filename)
    return path, len(content)
