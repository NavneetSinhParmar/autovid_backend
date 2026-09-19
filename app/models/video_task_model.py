from pydantic import BaseModel
from typing import Any, Optional
from datetime import datetime

class VideoTask(BaseModel):
    id: str
    company_id: str
    customer_id: str
    template_id: str
    status: str
    render_job_id: Optional[str] = None
    progress: int = 0       
    output_url: Optional[str] = None
    output_video_url: Optional[str] = None
    error: Optional[str] = None
    error_details: Optional[dict[str, Any]] = None
    download_count: int = 0
    created_at: datetime
    updated_at: datetime
