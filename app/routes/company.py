from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
from app.db.connection import db
from app.utils.auth import require_roles, hash_password

router = APIRouter(prefix="/company", tags=["Company Management"])

# 🟢 Create Company (SuperAdmin)
@router.post("/")
async def create_company(data: dict, user=Depends(require_roles("superadmin"))):
    # check duplicate username/email
    if await db.companies.find_one({"username": data["username"]}):
        raise HTTPException(status_code=400, detail="Username already exists")
    if await db.companies.find_one({"email": data["email"]}):
        raise HTTPException(status_code=400, detail="Email already exists")

    company_doc = {
        "company_name": data["company_name"],
        "email": data["email"],
        "mobile": data["mobile"],
        "description": data.get("description"),
        "logo_url": data.get("logo_url"),
        "username": data["username"],
        "password": hash_password(data["password"]),
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = await db.companies.insert_one(company_doc)
    return {"message": "Company created successfully", "id": str(result.inserted_id)}

# 🔵 Get all companies
@router.get("/")
async def list_companies(user=Depends(require_roles("superadmin"))):
    companies = []
    async for c in db.companies.find():
        c["id"] = str(c["_id"])
        del c["_id"], c["password"]
        companies.append(c)
    return companies

# 🟠 Get single company
@router.get("/{company_id}")
async def get_company(company_id: str, user=Depends(require_roles("superadmin"))):
    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    company["id"] = str(company["_id"])
    del company["_id"], company["password"]
    return company

# 🟣 Update company
@router.patch("/{company_id}")
async def update_company(company_id: str, data: dict, user=Depends(require_roles("superadmin"))):
    data["updated_at"] = datetime.utcnow()
    result = await db.companies.update_one({"_id": ObjectId(company_id)}, {"$set": data})
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Company not found or not updated")
    return {"message": "Company updated successfully"}

# 🔴 Delete company
@router.delete("/{company_id}")
async def delete_company(company_id: str, user=Depends(require_roles("superadmin"))):
    result = await db.companies.delete_one({"_id": ObjectId(company_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"message": "Company deleted successfully"}
