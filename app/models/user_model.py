from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Optional[str] = "customer"
    company_id: Optional[str] = None
    status: Optional[str] = "active"   # 👈 added

class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    status: str
