from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import datetime

class CustomerCreate(BaseModel):
    # Customer profile
    customer_company_name: Optional[str] = None
    full_name: str
    logo_url: Optional[str] = None
    city: Optional[str] = None
    phone_number: Optional[str] = None
    telephone_number: Optional[str] = None
    address: Optional[str] = None
    customer_category: Optional[str] = None
    
    # Relationships
    linked_company_id: Optional[str] = None 
    user_id: str     
    
    status: Optional[str] = "active"


class CustomerOut(BaseModel):
    id: str
    customer_company_name: Optional[str]
    full_name: str
    logo_url: Optional[str]
    city: Optional[str]
    phone_number: Optional[str]
    telephone_number: Optional[str]
    address: Optional[str]
    customer_category: Optional[str]  # NEW FIELD
    
    linked_company_id: Optional[str]
    user_id: str
    status: str
    created_at: datetime
    updated_at: datetime

class CustomerBulkUpdate(BaseModel):
    updates: List[CustomerCreate]