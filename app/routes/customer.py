from fastapi import APIRouter, HTTPException, Depends
from app.db.connection import db
from app.utils.auth import require_roles
from app.models.customer_model import CustomerCreate, CustomerOut
from bson import ObjectId

router = APIRouter(prefix="/customer", tags=["Customer"])

@router.post("/", response_model=CustomerOut)
async def create_customer(customer: CustomerCreate, user=Depends(require_roles("admin"))):
    # Admin can only add customers to their own company
    customer_dict = customer.dict()
    customer_dict["company_id"] = str(user["company_id"])
    existing = await db.customers.find_one({"email": customer.email})
    if existing:
        raise HTTPException(status_code=400, detail="Customer already exists")
    result = await db.customers.insert_one(customer_dict)
    new = await db.customers.find_one({"_id": result.inserted_id})
    new["id"] = str(new["_id"])
    return CustomerOut(**new)

@router.get("/", response_model=list[CustomerOut])
async def list_customers(user=Depends(require_roles("admin", "superadmin"))):
    query = {}
    if user["role"] == "admin":
        query = {"company_id": str(user["company_id"])}
    customers = []
    async for c in db.customers.find(query):
        c["id"] = str(c["_id"])
        customers.append(CustomerOut(**c))
    return customers

@router.get("/me", response_model=CustomerOut)
async def get_my_data(user=Depends(require_roles("customer"))):
    cust = await db.customers.find_one({"_id": ObjectId(user["_id"])})
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")
    cust["id"] = str(cust["_id"])
    return CustomerOut(**cust)
