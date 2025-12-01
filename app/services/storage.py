import os
import uuid
from typing import Tuple

LOCAL_MEDIA_ROOT = os.getenv("LOCAL_MEDIA_ROOT", "media_storage")

def save_file_local(file_obj, company_id: str, filename: str) -> Tuple[str, str]:
    """
    Returns:
        path: local system path
        url: public URL path for FastAPI
    """
    # Folder path
    folder = os.path.join(LOCAL_MEDIA_ROOT, company_id)
    os.makedirs(folder, exist_ok=True)

    # Unique filename
    safe_filename = filename.replace(" ", "_")
    unique = f"{uuid.uuid4().hex}_{safe_filename}"

    # Actual file path
    file_path = os.path.join(folder, unique)

    # Write file
    with open(file_path, "wb") as f:
        f.write(file_obj)

    # Convert file_path to public URL (fix backslashes)
    # url_path = f"/media_storage/{company_id}/{unique}"
    url_path = f"/public/media/{company_id}/{unique}"


    return file_path, url_path


async def save_upload_file(file, company_id: str) -> Tuple[str, str, int]:
    content = await file.read()

    file_path, url_path = save_file_local(
        content,
        company_id,
        file.filename
    )

    return file_path, url_path, len(content)
