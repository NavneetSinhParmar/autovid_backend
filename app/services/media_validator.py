import json
import os
import subprocess
import tempfile
import asyncio
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from app.core.errors import AppError
from app.core.settings import settings


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}
AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "ogg"}
IMAGE_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm", "application/octet-stream"}
AUDIO_MIMES = {
    "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac",
    "audio/ogg", "application/ogg", "application/octet-stream",
}


@dataclass(frozen=True)
class ValidatedMedia:
    content: bytes
    kind: str
    extension: str
    size: int
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None


def _error(code: str, message: str, status: int = 400) -> AppError:
    return AppError(status, code, message)


def _extension(file: UploadFile) -> str:
    filename = Path(file.filename or "").name
    if not filename or "." not in filename:
        raise _error("UNSUPPORTED_FORMAT", "A supported file extension is required")
    return filename.rsplit(".", 1)[1].lower()


async def _read_limited(file: UploadFile, maximum: int) -> bytes:
    data = await file.read(maximum + 1)
    if len(data) > maximum:
        raise _error("FILE_TOO_LARGE", "Uploaded file exceeds the configured size limit", 413)
    if not data:
        raise _error("INVALID_MEDIA_TYPE", "Uploaded file is empty")
    return data


def _probe(content: bytes, suffix: str) -> dict:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        command = [
            os.getenv("FFPROBE_BIN", "ffprobe"), "-v", "error",
            "-show_entries", "format=duration,format_name:stream=index,codec_type,codec_name,width,height",
            "-of", "json", tmp_path,
        ]
        result = subprocess.run(
            command, capture_output=True, text=True,
            timeout=min(settings.ffmpeg_timeout_seconds, 60), check=False,
        )
        if result.returncode != 0:
            raise _error("INVALID_VIDEO", "Media file is corrupt or cannot be decoded")
        return json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise AppError(503, "MEDIA_PROBE_UNAVAILABLE", "FFprobe is not installed") from exc
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise _error("INVALID_VIDEO", "Media file could not be inspected") from exc
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


async def validate_image(file: UploadFile) -> ValidatedMedia:
    extension = _extension(file)
    if extension not in IMAGE_EXTENSIONS:
        raise _error("UNSUPPORTED_FORMAT", "Allowed image formats: JPG, JPEG, PNG, WebP")
    if (file.content_type or "").lower() not in IMAGE_MIMES:
        raise _error("INVALID_MEDIA_TYPE", "File MIME type does not match an allowed image")
    content = await _read_limited(file, settings.max_image_bytes)
    width, height = await asyncio.to_thread(_inspect_image, content)
    if width > settings.max_image_width or height > settings.max_image_height:
        raise _error(
            "IMAGE_DIMENSIONS_EXCEEDED",
            f"Image dimensions may not exceed {settings.max_image_width}x{settings.max_image_height}",
        )
    return ValidatedMedia(content, "image", extension, len(content), width=width, height=height)


def _inspect_image(content: bytes) -> tuple[int, int]:
    try:
        from io import BytesIO
        from PIL import Image, UnidentifiedImageError
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            image.verify()
    except ImportError as exc:
        raise AppError(503, "IMAGE_VALIDATOR_UNAVAILABLE", "Pillow is not installed") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise _error("INVALID_MEDIA_TYPE", "Image is corrupt or cannot be decoded") from exc
    return width, height


async def validate_video(file: UploadFile, max_duration: float | None = None) -> ValidatedMedia:
    extension = _extension(file)
    if extension not in VIDEO_EXTENSIONS:
        raise _error("UNSUPPORTED_FORMAT", "Allowed video formats: MP4, MOV, WebM")
    if (file.content_type or "").lower() not in VIDEO_MIMES:
        raise _error("INVALID_MEDIA_TYPE", "File MIME type does not match an allowed video")
    content = await _read_limited(file, settings.max_video_bytes)
    probe = await asyncio.to_thread(_probe, content, extension)
    streams = probe.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise _error("INVALID_VIDEO", "No decodable video stream was found")
    try:
        duration = float((probe.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        raise _error("INVALID_VIDEO", "Video duration could not be determined")
    return ValidatedMedia(
        content, "video", extension, len(content), duration=duration,
        width=video_stream.get("width"), height=video_stream.get("height"),
        codec=video_stream.get("codec_name"),
    )


async def validate_audio(file: UploadFile) -> ValidatedMedia:
    extension = _extension(file)
    if extension not in AUDIO_EXTENSIONS:
        raise _error("UNSUPPORTED_FORMAT", "Unsupported audio format")
    if (file.content_type or "").lower() not in AUDIO_MIMES:
        raise _error("INVALID_MEDIA_TYPE", "File MIME type does not match an allowed audio file")
    content = await _read_limited(file, settings.max_audio_bytes)
    probe = await asyncio.to_thread(_probe, content, extension)
    audio_stream = next((s for s in (probe.get("streams") or []) if s.get("codec_type") == "audio"), None)
    if not audio_stream:
        raise _error("INVALID_MEDIA_TYPE", "No decodable audio stream was found")
    try:
        duration = float((probe.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        raise _error("INVALID_MEDIA_TYPE", "Audio duration could not be determined")
    if duration > settings.max_audio_seconds:
        raise _error("VIDEO_TOO_LONG", f"Audio duration may not exceed {int(settings.max_audio_seconds)} seconds")
    return ValidatedMedia(content, "audio", extension, len(content), duration=duration, codec=audio_stream.get("codec_name"))


async def validate_media(file: UploadFile) -> ValidatedMedia:
    extension = _extension(file)
    if extension in IMAGE_EXTENSIONS:
        return await validate_image(file)
    if extension in VIDEO_EXTENSIONS:
        return await validate_video(file)
    if extension in AUDIO_EXTENSIONS:
        return await validate_audio(file)
    raise _error("UNSUPPORTED_FORMAT", "Unsupported media format")
