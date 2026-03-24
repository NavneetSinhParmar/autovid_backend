from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "active"
    company_id: Optional[str] = None 

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class CategoryOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    company_id: str              
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True   
