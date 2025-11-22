from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

class PublicVideoLink(BaseModel):
    id: str
    customer_id: str
    video_task_id: str
    token: str
    expires_at: datetime
