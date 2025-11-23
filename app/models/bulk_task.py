from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

class BulkTask(BaseModel):
    id: str
    template_id: str
    company_id: str

    total_customers: int
    completed_count: int = 0

    status: str          # pending / processing / completed

    created_at: datetime
