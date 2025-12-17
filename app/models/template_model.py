from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

class Template(BaseModel):
    id: str
    company_id: str
    template_name: str
    category: str
    base_video_url: Optional[str]
    base_image_url: Optional[str]
    base_audio_url: Optional[str]

    duration: float
    trim: Optional[dict]         # {start, end}

    template_json: dict         # full layers JSON (text, img, audio)

    status: str = "active"
    created_at: datetime
    updated_at: datetime
