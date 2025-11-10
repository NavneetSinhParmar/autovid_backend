from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class CompanyBase(BaseModel):
    company_name: str
    email: EmailStr
    mobile: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    username: str
    password: str
    status: Optional[str] = "active"

class CompanyOut(BaseModel):
    id: str
    company_name: str
    email: str
    mobile: str
    description: Optional[str]
    logo_url: Optional[str]
    username: str
    status: str
    created_at: datetime
    updated_at: datetime
