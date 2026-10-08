import asyncio
from dataclasses import replace

from app.core.settings import settings
from app.services import media_validator
from app.services.storage import storage_service

_upload_slots = asyncio.Semaphore(settings.upload_processing_concurrency)


async def validate_and_store_media(file, folder: str):
    # Hold the slot through inspection and disk write, before reading into RAM.
    async with _upload_slots:
        media = await media_validator.validate_media(file)
        path = await asyncio.to_thread(
            storage_service.save_cached, media.content, folder,
            f"upload.{media.extension}",
        )
        return replace(media, content=b""), path
