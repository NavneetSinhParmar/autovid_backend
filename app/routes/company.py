from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from datetime import datetime
from bson import ObjectId
from app.db.connection import db
from app.utils.auth import require_roles, hash_password
from app.services.storage import save_company_file
from typing import Optional
from app.services.url import build_media_url
from fastapi import Request

router = APIRouter(prefix="/company", tags=["Company Management"])

@router.post("/")
async def create_company(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    company_name: str = Form(...),
    mobile: str = Form(...),
    description: str = Form(None),
    logo_file: UploadFile = File(None),
    user=Depends(require_roles("superadmin")),
):

    # ---- STEP 1: Check if user already exists ----
    if await db.users.find_one({"username": username}):
        raise HTTPException(status_code=400, detail="Username already exists")

    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already exists")

    # ---- STEP 2: Create User Entry ----
    user_doc = {
        "username": username,
        "email": email,
        "password": hash_password(password),
        "role": "company",
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    user_result = await db.users.insert_one(user_doc)
    user_id = str(user_result.inserted_id)

    # ---- STEP 3: Handle LOGO upload (optional) ----
    logo_url = None
    if logo_file:
        local_path, size = await save_company_file(logo_file, user_id)

        logo_url = local_path      
                     # local disk path

    # ---- STEP 4: Create Company Entry ----
    company_doc = {
        "company_name": company_name,
        "description": description,
        "mobile": mobile,
        "logo_url": logo_url,
        "user_id": user_id,
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    company_result = await db.companies.insert_one(company_doc)

    return {
        "message": "Company created successfully",
        "company_id": str(company_result.inserted_id),
        "user_id": user_id,
        "logo_url": build_media_url(logo_url)
    }

# 🔵 Get all companies
@router.get("/")
async def list_companies(request: Request, user=Depends(require_roles("superadmin"))):
    companies = []

    async for c in db.companies.find():

        # fix company id
        c["company_id"] = str(c["_id"])
        c.pop("_id", None)

         # ✅ FIX LOGO URL HERE
        if c.get("logo_url"):
            c["logo_url"] = f"media/{c['logo_url']}"

        # join user
        user_data = await db.users.find_one(
            {"_id": ObjectId(c["user_id"])},
            {"password": 0}
        )

        if user_data:
            # convert user fields
            user_data["user_id"] = str(user_data["_id"])
            user_data.pop("_id", None)

            # DO NOT MERGE DIRECTLY (this overrides ids)
            # Instead rename and add
            c["username"] = user_data["username"]
            c["email"] = user_data["email"]
            c["role"] = user_data["role"]
            c["user_status"] = user_data["status"]
            c["user_created_at"] = user_data["created_at"]
            c["user_updated_at"] = user_data["updated_at"]

        companies.append(c)

    return companies


# 🟠 Get single company by ID

@router.get("/{company_id}")
async def get_company_detail(company_id: str,request: Request):
    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(404, "Company not found")

    company["company_id"] = str(company["_id"])
    company.pop("_id", None)

    # 🔥 Convert logo path to public URL
    if company.get("logo_url"):
        company["logo_url"] = f"{request.base_url}media/{company['logo_url']}"

    return company


# 🟣 Update company
@router.patch("/{company_id}")
async def update_company(
    company_id: str,

    company_name: Optional[str] = Form(None),
    mobile: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    status: Optional[str] = Form(None),

    logo_file: Optional[UploadFile] = File(None),

    user=Depends(require_roles("superadmin"))
):

    # ---- STEP 1: Check company exists ----
    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # ---- STEP 2: Prepare update data ----
    update_data = {}

    if company_name is not None:
        update_data["company_name"] = company_name

    if mobile is not None:
        update_data["mobile"] = mobile

    if description is not None:
        update_data["description"] = description

    if status is not None:
        update_data["status"] = status

    # ---- STEP 3: Handle logo upload ----
    if logo_file:
        local_path, size = await save_company_file(logo_file, company["user_id"])
        update_data["logo_url"] = local_path

    if not update_data:
        raise HTTPException(status_code=400, detail="No data provided for update")

    update_data["updated_at"] = datetime.utcnow()

    # ---- STEP 4: Update DB ----
    await db.companies.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": update_data}
    )

    return {
        "message": "Company updated successfully",
        "updated_fields": list(update_data.keys())
    }


# 🔴 Delete company (also delete linked user)
@router.delete("/{company_id}")
async def delete_company(
    company_id: str,
    user=Depends(require_roles("superadmin"))
):

    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # 🔥 Convert user_id safely
    try:
        user_object_id = ObjectId(company["user_id"])
    except Exception:
        raise HTTPException(500, "Invalid user_id stored in company")

    # Delete company
    await db.companies.delete_one({"_id": ObjectId(company_id)})

    # Delete linked user
    result = await db.users.delete_one({"_id": user_object_id})

    if result.deleted_count == 0:
        raise HTTPException(500, "Linked user not found or already deleted")

    return {
        "message": "Company and linked user deleted successfully",
        "deleted_user_id": str(user_object_id)
    }

