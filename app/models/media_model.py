from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

class Media(BaseModel):
    id: str
    company_id: str
    file_url: str
    file_type: str      # image / video / audio
    original_name: str
    size: int
    created_at: datetime
