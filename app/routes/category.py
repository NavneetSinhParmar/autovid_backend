from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime
from typing import Dict

from app.db.connection import db
from app.models.category import (
    CategoryCreate,
    CategoryUpdate,
    CategoryOut,
)
from app.utils.auth import require_roles

router = APIRouter(prefix="/category", tags=["Category"])


async def _resolve_company_id_for_user(user: Dict, explicit_company_id: str | None = None) -> str:
    """
    Determine which company_id a category operation should use.
    - superadmin: must pass company_id (either in payload or query param)
    - company: resolved via companies.user_id == user["_id"]
    """
    role = user.get("role")

    if role == "superadmin":
        if not explicit_company_id:
            raise HTTPException(
                status_code=400,
                detail="company_id is required for superadmin operations on categories",
            )
        return str(explicit_company_id)

    # Company user – look up their company document
    company = await db.companies.find_one({"user_id": str(user["_id"])})
    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found for current user",
        )
    return str(company["_id"])


async def _get_company_filter(user: Dict) -> Dict:
    """
    Filter used for list/get/update/delete:
    - superadmin: no filter (see all companies' categories)
    - company: restricted to their own company_id
    """
    role = user.get("role")
    if role == "superadmin":
        return {}

    company_id = await _resolve_company_id_for_user(user, explicit_company_id=None)
    return {"company_id": company_id}


@router.post("/", response_model=CategoryOut)
async def create_category(
    payload: CategoryCreate,
    user=Depends(require_roles("superadmin", "company"))
):
    # Decide which company this category belongs to
    company_id = await _resolve_company_id_for_user(
        user,
        explicit_company_id=str(payload.company_id) if getattr(payload, "company_id", None) else None,
    )

    existing = await db.categories.find_one({
        "name": payload.name,
        "company_id": company_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")

    now = datetime.utcnow()
    doc = {
        "name": payload.name,
        "description": payload.description,
        "status": payload.status,
        "company_id": company_id,
        "created_at": now,
        "updated_at": now
    }

    result = await db.categories.insert_one(doc)
    doc["_id"] = result.inserted_id

    return {"id": str(doc["_id"]), **doc}


@router.get("/", response_model=list[CategoryOut])
async def get_categories(
    user=Depends(require_roles("superadmin", "company"))
):
    base_filter = await _get_company_filter(user)
    categories = []
    async for cat in db.categories.find(base_filter):
        categories.append({"id": str(cat["_id"]), **cat})
    return categories


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(
    category_id: str,
    user=Depends(require_roles("superadmin", "company"))
):
    if not ObjectId.is_valid(category_id):
        raise HTTPException(status_code=400, detail="Invalid category id")

    query = {"_id": ObjectId(category_id), **(await _get_company_filter(user))}
    category = await db.categories.find_one(query)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    return {"id": str(category["_id"]), **category}


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: str,
    payload: CategoryUpdate,
    user=Depends(require_roles("superadmin", "company"))
):
    if not ObjectId.is_valid(category_id):
        raise HTTPException(status_code=400, detail="Invalid category id")

    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    update_data.pop("company_id", None)

    if not update_data:
        raise HTTPException(status_code=400, detail="Nothing to update")

    update_data["updated_at"] = datetime.utcnow()

    query = {"_id": ObjectId(category_id), **(await _get_company_filter(user))}
    result = await db.categories.update_one(query, {"$set": update_data})

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")

    category = await db.categories.find_one({"_id": ObjectId(category_id)})
    return {"id": str(category["_id"]), **category}


@router.delete("/{category_id}")
async def delete_category(
    category_id: str,
    user=Depends(require_roles("superadmin", "company"))
):
    if not ObjectId.is_valid(category_id):
        raise HTTPException(status_code=400, detail="Invalid category id")

    query = {"_id": ObjectId(category_id), **(await _get_company_filter(user))}
    result = await db.categories.delete_one(query)

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")

    return {"message": "Category deleted"}