from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

class BulkTaskCustomer(BaseModel):
    id: str
    bulk_task_id: str
    customer_id: str
    video_task_id: str  # link → video_tasks.collection
