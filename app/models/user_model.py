from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: Optional[str] = "customer"   # superadmin / company / customer
    status: Optional[str] = "active"


class UserOut(BaseModel):
    id: str
    username: str
    email: EmailStr
    role: str
    status: str
