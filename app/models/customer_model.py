from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

class CustomerCreate(BaseModel):
    customer_company_name: Optional[str] = None
    full_name: str
    email: Optional[str] = None
    distributed_id: Optional[str] = None
    logo_url: Optional[str] = None
    city: Optional[str] = None
    phone_number: Optional[str] = None
    telephone_number: Optional[str] = None
    address: Optional[str] = None
    customer_category: Optional[str] = None
    linked_company_id: Optional[str] = None
    user_id: Optional[str] = None
    status: Optional[str] = "active"


class CustomerOut(BaseModel):
    id: str
    customer_company_name: Optional[str]
    full_name: str
    email: Optional[str] = None
    distributed_id: Optional[str] = None
    logo_url: Optional[str]
    city: Optional[str]
    phone_number: Optional[str]
    telephone_number: Optional[str]
    address: Optional[str]
    customer_category: Optional[str]
    linked_company_id: Optional[str]
    user_id: str
    status: str
    created_at: datetime
    updated_at: datetime

class CustomerBulkUpdate(BaseModel):
    updates: List[CustomerCreate]