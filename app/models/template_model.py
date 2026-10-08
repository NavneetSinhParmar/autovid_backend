from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from datetime import datetime


BASE_MEDIA_FIELDS = ("base_video_url", "base_image_url", "base_audio_url")


def _primary_media_url(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)):
        for item in reversed(value):
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    return value

class Template(BaseModel):
    id: str
    company_id: str
    template_name: str
    category: str
    preview_image_url: Optional[str]
    base_video_url: Optional[str]
    base_image_url: Optional[str]
    base_audio_url: Optional[str]
    type: Optional[str] = "video"
    duration: float
    trim: Optional[dict]
    template_json: dict 
    public: bool = True
    status: str = "active"
    created_at: datetime
    updated_at: datetime
    public_download_count: int = 0
    private_download_count: int = 0


class TemplateCreate(BaseModel):
    template_name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="general", max_length=100)
    preview_image_url: str | None = None
    base_video_url: str | None = None
    base_image_url: str | None = None
    base_audio_url: str | None = None
    duration: float | None = Field(default=None, ge=0)
    trim: dict[str, Any] | None = None
    template_json: dict[str, Any] = Field(default_factory=dict)
    type: str = Field(default="video", pattern="^(video|image|img)$")
    public: bool = False

    @field_validator(*BASE_MEDIA_FIELDS, mode="before")
    @classmethod
    def select_primary_media_url(cls, value: Any):
        return _primary_media_url(value)


class TemplateUpdate(BaseModel):
    template_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    preview_image_url: str | None = None
    base_video_url: str | None = None
    base_image_url: str | None = None
    base_audio_url: str | None = None
    duration: float | None = Field(default=None, ge=0)
    trim: dict[str, Any] | None = None
    template_json: dict[str, Any] | None = None
    type: str | None = Field(default=None, pattern="^(video|image|img)$")
    public: bool | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")

    @field_validator(*BASE_MEDIA_FIELDS, mode="before")
    @classmethod
    def select_primary_media_url(cls, value: Any):
        return _primary_media_url(value)
    
