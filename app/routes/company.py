from fastapi import APIRouter, HTTPException, Depends
from app.db.connection import db
from app.utils.auth import require_roles
from app.models.company_model import CompanyCreate, CompanyOut
from bson import ObjectId

router = APIRouter(prefix="/company", tags=["Company"])

@router.post("/", response_model=CompanyOut)
async def create_company(company: CompanyCreate, user=Depends(require_roles("superadmin"))):
    existing = await db.companies.find_one({"email": company.email})
    if existing:
        raise HTTPException(status_code=400, detail="Company already exists")
    result = await db.companies.insert_one(company.dict())
    new = await db.companies.find_one({"_id": result.inserted_id})
    return {
        "id": str(new["_id"]),
        "name": new["name"],
        "email": new["email"],
        "phone": new.get("phone"),
        "description": new.get("description"),
        "status": new["status"]
    }

@router.get("/", response_model=list[CompanyOut])
async def list_companies(user=Depends(require_roles("superadmin"))):
    companies = []
    async for c in db.companies.find({}):
        c["id"] = str(c["_id"])
        companies.append(CompanyOut(**c))
    return companies

@router.delete("/{company_id}")
async def delete_company(company_id: str, user=Depends(require_roles("superadmin"))):
    res = await db.companies.delete_one({"_id": ObjectId(company_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"message": "Company deleted successfully"}
