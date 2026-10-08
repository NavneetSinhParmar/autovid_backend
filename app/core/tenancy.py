from bson import ObjectId
from fastapi import HTTPException

from app.db.connection import db


def object_id(value: str, label: str = "id") -> ObjectId:
    if not ObjectId.is_valid(str(value)):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return ObjectId(str(value))


async def company_id_for_user(user: dict, explicit_company_id: str | None = None) -> str:
    if user.get("role") == "superadmin":
        if not explicit_company_id:
            raise HTTPException(status_code=400, detail="company_id is required")
        company = await db.companies.find_one({"_id": object_id(explicit_company_id, "company_id")})
    elif user.get("role") == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})
    else:
        raise HTTPException(status_code=403, detail="Company access required")
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return str(company["_id"])


def company_object_id_filter(company_id: str) -> dict:
    """Compatibility filter while legacy customer rows still contain ObjectIds."""
    values: list[object] = [company_id]
    if ObjectId.is_valid(company_id):
        values.append(ObjectId(company_id))
    return {"$in": values}


async def owned_template(template_id: str, company_id: str) -> dict:
    template = await db.templates.find_one({"_id": object_id(template_id, "template_id"), "company_id": company_id})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


async def owned_customer(customer_id: str, company_id: str) -> dict:
    customer = await db.customers.find_one({
        "_id": object_id(customer_id, "customer_id"),
        "linked_company_id": company_object_id_filter(company_id),
    })
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
