from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    status: Optional[str] = "active"

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class CategoryOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
