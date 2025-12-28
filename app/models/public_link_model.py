from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class PublicVideoLink(BaseModel):
    id: str
    video_task_id: str
    token: str
    is_active: bool = True
    expires_at: Optional[datetime] = None
    created_at: datetime
