from fastapi import APIRouter, HTTPException, Depends
from app.db.connection import db
from app.utils.auth import require_roles
from bson import ObjectId

router = APIRouter(prefix="/admin", tags=["Admin Management"])

# 🟢 1. List all admins (SuperAdmin only)
@router.get("/")
async def list_admins(user=Depends(require_roles("superadmin"))):
    admins = []
    async for a in db.users.find({"role": "admin"}):
        a["id"] = str(a["_id"])
        del a["_id"]
        del a["password"]
        admins.append(a)
    return admins


# 🟡 2. Get single admin details (SuperAdmin only)
@router.get("/{admin_id}")
async def get_admin(admin_id: str, user=Depends(require_roles("superadmin"))):
    admin = await db.users.find_one({"_id": ObjectId(admin_id), "role": "admin"})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    admin["id"] = str(admin["_id"])
    del admin["_id"]
    del admin["password"]
    return admin


# 🔵 3. Update admin status (SuperAdmin only)
@router.patch("/{admin_id}/status")
async def update_admin_status(admin_id: str, data: dict, user=Depends(require_roles("superadmin"))):
    new_status = data.get("status")
    if new_status not in ["active", "inactive"]:
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'inactive'")
    
    result = await db.users.update_one(
        {"_id": ObjectId(admin_id), "role": "admin"},
        {"$set": {"status": new_status}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Admin not found or no change made")
    
    return {"message": f"Admin status updated to '{new_status}'"}
