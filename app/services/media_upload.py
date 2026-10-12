import asyncio
from dataclasses import replace
from pathlib import Path

from app.core.settings import settings
from app.services import media_validator
from app.services.storage import storage_service

_upload_slots = asyncio.Semaphore(settings.upload_processing_concurrency)


async def validate_and_store_media(file, folder: str):
    # Hold the slot through inspection and disk write, before reading into RAM.
    async with _upload_slots:
        if media_validator._extension(file) in media_validator.VIDEO_EXTENSIONS:
            media = await media_validator.validate_video(file, stream_to_disk=True)
        else:
            media = await media_validator.validate_media(file)
        try:
            if media.temporary_path:
                path = await asyncio.to_thread(storage_service.save_cached_file, media.temporary_path, folder, f"upload.{media.extension}")
            else:
                path = await asyncio.to_thread(storage_service.save_cached, media.content, folder, f"upload.{media.extension}")
            return replace(media, content=b"", temporary_path=None), path
        finally:
            if media.temporary_path:
                Path(media.temporary_path).unlink(missing_ok=True)
