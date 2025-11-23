from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

class VideoTask(BaseModel):
    id: str               # Celery task id
    customer_id: str
    company_id: str
    template_id: str

    status: str           # pending/processing/completed/failed
    render_progress: int  # 0–100 %

    output_url: Optional[str]
    
    created_at: datetime
    updated_at: datetime
