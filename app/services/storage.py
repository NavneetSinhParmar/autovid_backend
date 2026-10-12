import os
import shutil
import uuid
import hashlib
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
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
    safe_name = Path(filename or "upload.bin").name.replace(" ", "_")
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    full_path = get_media_abs_path(f"{folder_path}/{unique_name}")

    with open(full_path, "wb") as f:
        f.write(file_obj)

    return f"{folder_path}/{unique_name}"


async def save_company_file(file, company_user_id: str):
    content = await file.read()
    path = storage_service.save(content, company_user_id, file.filename)
    return path, len(content)


async def save_customer_file(file, company_id: str, customer_id: str):
    content = await file.read()
    folder = customer_folder_path(company_id, customer_id)
    path = storage_service.save(content, folder, file.filename)
    return path, len(content)


def save_file_local_for_media(file_obj: bytes, folder_path: str, filename: str) -> str:
    return save_file_local(file_obj, folder_path, filename)


async def save_upload_file(file, company_id: str, folder_path: str | None = None) -> Tuple[str, int]:
    content = await file.read()
    path = storage_service.save(content, folder_path or company_id, file.filename)
    return path, len(content)


class StorageService(ABC):
    def save_cached_file(self, source: str, folder_path: str, filename: str) -> str:
        raise NotImplementedError("Storage adapter must support streaming file uploads")

    def save_cached(self, content: bytes, folder_path: str, filename: str) -> str:
        return self.save(content, folder_path, filename)

    @abstractmethod
    def save(self, content: bytes, folder_path: str, filename: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def delete(self, relative_path: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def absolute_path(self, relative_path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def exists(self, relative_path: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def ensure_folder(self, folder_path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def delete_folder(self, folder_path: str) -> bool:
        raise NotImplementedError


class LocalStorageService(StorageService):
    def save_cached_file(self, source: str, folder_path: str, filename: str) -> str:
        folder = ensure_media_folder(folder_path)
        digest = hashlib.sha256()
        with open(source, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        relative = f"{folder}/{digest.hexdigest()}{Path(filename).suffix.lower()}"
        target = get_media_abs_path(relative)
        if os.path.isfile(target):
            return relative
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(target), delete=False) as handle:
                temporary = handle.name
                with open(source, "rb") as input_file:
                    shutil.copyfileobj(input_file, handle, 1024 * 1024)
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
        return relative

    def save_cached(self, content: bytes, folder_path: str, filename: str) -> str:
        folder = ensure_media_folder(folder_path)
        suffix = Path(filename).suffix.lower() or ".bin"
        digest = hashlib.sha256(content).hexdigest()
        relative = f"{folder}/{digest}{suffix}"
        target = get_media_abs_path(relative)
        if os.path.isfile(target):
            return relative
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(target), delete=False) as handle:
                temporary = handle.name
                handle.write(content)
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass  # A concurrent upload already published these bytes.
        finally:
            if temporary and os.path.isfile(temporary):
                os.remove(temporary)
        return relative

    def save(self, content: bytes, folder_path: str, filename: str) -> str:
        return save_file_local(content, folder_path, filename)

    def delete(self, relative_path: str) -> bool:
        return delete_media_file(relative_path)

    def absolute_path(self, relative_path: str) -> str:
        return get_media_abs_path(relative_path)

    def exists(self, relative_path: str) -> bool:
        return os.path.isfile(get_media_abs_path(relative_path))

    def ensure_folder(self, folder_path: str) -> str:
        return ensure_media_folder(folder_path)

    def delete_folder(self, folder_path: str) -> bool:
        return delete_media_folder(folder_path)


storage_service: StorageService = LocalStorageService()


async def save_template_file(file, company_id: str, template_id: str) -> Tuple[str, int]:
    return await save_upload_file(file, company_id, template_folder_path(company_id, template_id))


async def save_customer_logo_file(file, company_id: str, customer_id: str) -> Tuple[str, int]:
    return await save_customer_file(file, company_id, customer_id)
