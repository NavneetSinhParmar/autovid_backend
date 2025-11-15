from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class CompanyCreate(BaseModel):
    company_name: str
    description: Optional[str] = None
    mobile: str
    logo_url: Optional[str] = None
    user_id: str                     # FK to User table
    status: Optional[str] = "active"


class CompanyOut(BaseModel):
    id: str
    company_name: str
    description: Optional[str]
    mobile: str
    logo_url: Optional[str]
    user_id: str
    status: str
    created_at: datetime
    updated_at: datetime
