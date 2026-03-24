from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

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
    
