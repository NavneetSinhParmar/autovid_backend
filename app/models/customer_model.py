from pydantic import BaseModel, EmailStr
from typing import Optional

class CustomerCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    city: Optional[str] = None
    company_id: Optional[str] = None   # auto-filled from admin
    status: Optional[str] = "active"

class CustomerOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    phone: Optional[str] = None
    city: Optional[str] = None
    status: str
