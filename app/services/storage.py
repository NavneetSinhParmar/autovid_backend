import os
import shutil
import uuid
from typing import Tuple

LOCAL_MEDIA_ROOT = os.getenv("LOCAL_MEDIA_ROOT", "./media")


def _media_root_abs() -> str:
    return os.path.abspath(LOCAL_MEDIA_ROOT)


def _safe_relative_path(folder_path: str) -> str:
    folder_path = str(folder_path or "").replace("\\", "/").strip("/")
    if not folder_path:
        raise ValueError("folder_path is required")
    if os.path.isabs(folder_path) or ".." in folder_path.split("/"):
        raise ValueError("Invalid media folder path")
    return folder_path


def get_media_abs_path(relative_path: str) -> str:
    relative_path = str(relative_path or "").replace("\\", "/").strip("/")
    if not relative_path or os.path.isabs(relative_path) or ".." in relative_path.split("/"):
        raise ValueError("Invalid media path")

    root = _media_root_abs()
    full_path = os.path.abspath(os.path.join(root, *relative_path.split("/")))
    if os.path.commonpath([root, full_path]) != root:
        raise ValueError("Media path escapes media root")
    return full_path


def ensure_media_folder(folder_path: str) -> str:
    folder_path = _safe_relative_path(folder_path)
    os.makedirs(get_media_abs_path(folder_path), exist_ok=True)
    return folder_path


def delete_media_folder(folder_path: str) -> bool:
    folder_path = _safe_relative_path(folder_path)
    full_path = get_media_abs_path(folder_path)
    if os.path.isdir(full_path):
        shutil.rmtree(full_path)
        return True
    return False


def delete_media_file(relative_path: str) -> bool:
    full_path = get_media_abs_path(relative_path)
    if os.path.isfile(full_path):
        os.remove(full_path)
        return True
    return False


def customer_folder_path(company_id: str, customer_id: str) -> str:
    return f"{company_id}/customers/{customer_id}"


def template_folder_path(company_id: str, template_id: str) -> str:
    return f"{company_id}/templates/{template_id}"


def save_file_local(file_obj: bytes, folder_path: str, filename: str) -> str:
    folder_path = ensure_media_folder(folder_path)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    full_path = get_media_abs_path(f"{folder_path}/{unique_name}")

    with open(full_path, "wb") as f:
        f.write(file_obj)

    return f"{folder_path}/{unique_name}"


async def save_company_file(file, company_user_id: str):
    content = await file.read()
    path = save_file_local(content, company_user_id, file.filename)
    return path, len(content)


async def save_customer_file(file, company_id: str, customer_id: str):
    content = await file.read()
    folder = customer_folder_path(company_id, customer_id)
    path = save_file_local(content, folder, file.filename)
    return path, len(content)


def save_file_local_for_media(file_obj: bytes, folder_path: str, filename: str) -> str:
    print(f"Saving file in media folder {folder_path} with filename {filename}")
    folder_path = ensure_media_folder(folder_path)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    full_path = get_media_abs_path(f"{folder_path}/{unique_name}")
    print("Saving file to:", full_path)

    with open(full_path, "wb") as f:
        f.write(file_obj)

    # Return relative path without a media prefix; url.py adds /media/ when needed.
    return f"{folder_path}/{unique_name}"


async def save_upload_file(file, company_id: str, folder_path: str | None = None) -> Tuple[str, int]:
    print("Saving uploaded file for company:", company_id)
    content = await file.read()
    path = save_file_local_for_media(content, folder_path or company_id, file.filename)
    return path, len(content)


async def save_template_file(file, company_id: str, template_id: str) -> Tuple[str, int]:
    return await save_upload_file(file, company_id, template_folder_path(company_id, template_id))


async def save_customer_logo_file(file, company_id: str, customer_id: str) -> Tuple[str, int]:
    return await save_customer_file(file, company_id, customer_id)
