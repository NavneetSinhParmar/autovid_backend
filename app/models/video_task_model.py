from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class VideoTask(BaseModel):
    id: str
    company_id: str
    customer_id: str
    template_id: str

    status: str              # pending | processing | completed | failed
    progress: int = 0        # 0–100

    output_video_url: Optional[str] = None
    error: Optional[str] = None
    download_count: int = 0
    
    created_at: datetime
    updated_at: datetime
