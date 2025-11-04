from pydantic import BaseModel, EmailStr
from typing import Optional

class CompanyCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    description: Optional[str] = None
    logo: Optional[str] = None
    status: Optional[str] = "active"

class CompanyOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    phone: Optional[str] = None
    description: Optional[str] = None
    status: str
