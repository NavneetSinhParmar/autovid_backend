from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime
from app.db.connection import db
from app.models.category import (
    CategoryCreate,
    CategoryUpdate,
    CategoryOut
)
from app.utils.auth import require_roles

router = APIRouter(prefix="/categories", tags=["Categories"])

@router.post("/", response_model=CategoryOut)
async def create_category(payload: CategoryCreate):

    # duplicate check
    existing = await db.categories.find_one({"name": payload.name})
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")

    now = datetime.utcnow()

    doc = {
        "name": payload.name,
        "description": payload.description,
        "status": payload.status,
        "created_at": now,
        "updated_at": now
    }

    result = await db.categories.insert_one(doc)
    doc["_id"] = result.inserted_id

    return {
        "id": str(doc["_id"]),
        **doc
    }

@router.get("/", response_model=list[CategoryOut])
async def get_categories():

    categories = []
    async for cat in db.categories.find():
        categories.append({
            "id": str(cat["_id"]),
            **cat
        })

    return categories

@router.put("/{category_id}", response_model=CategoryOut)
async def update_category(category_id: str, payload: CategoryUpdate):

    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nothing to update")

    update_data["updated_at"] = datetime.utcnow()

    result = await db.categories.update_one(
        {"_id": ObjectId(category_id)},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")

    category = await db.categories.find_one({"_id": ObjectId(category_id)})

    return {
        "id": str(category["_id"]),
        **category
    }

@router.delete("/{category_id}")
async def delete_category(
    category_id: str,
    user=Depends(require_roles("superadmin", "company"))
):
    query = {"_id": ObjectId(category_id)}

    if user["role"] == "company":
        query["company_id"] = ObjectId(user["company_id"])

    result = await db.categories.delete_one(query)

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")

    return {"message": "Category deleted"}
