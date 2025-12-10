from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from datetime import datetime
from bson import ObjectId
from app.db.connection import db
from app.utils.auth import require_roles, hash_password
from app.services.storage import save_upload_file

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
    user=Depends(require_roles("superadmin"))
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
        local_path, size = await save_upload_file(logo_file, user_id)

        logo_url = local_path                     # local disk path

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
        "logo_url": logo_url
    }

# 🔵 Get all companies
@router.get("/")
async def list_companies(user=Depends(require_roles("superadmin"))):
    companies = []

    async for c in db.companies.find():

        # fix company id
        c["company_id"] = str(c["_id"])
        c.pop("_id", None)

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


# 🟠 Get single company
@router.get("/{company_id}")
async def list_companies(user=Depends(require_roles("superadmin"))):
    companies = []

    async for c in db.companies.find():

        # Convert company ID
        company_id = str(c["_id"])
        c["id"] = company_id
        c.pop("_id", None)

        # Fetch user
        user_data = await db.users.find_one(
            {"_id": ObjectId(c["user_id"])},
            {"password": 0}
        )

        # Merge user fields at root level without overriding company data
        if user_data:
            c["user_id"] = str(user_data["_id"])
            c["username"] = user_data["username"]
            c["email"] = user_data["email"]
            c["role"] = user_data["role"]

            # optionally add these:
            c["user_status"] = user_data["status"]
            c["user_created_at"] = user_data["created_at"]
            c["user_updated_at"] = user_data["updated_at"]

        companies.append(c)

    return companies


# 🟣 Update company
@router.patch("/{company_id}")
async def update_company(company_id: str, data: dict, user=Depends(require_roles("superadmin"))):

    # Prevent updating user_id manually
    if "user_id" in data:
        del data["user_id"]

    data["updated_at"] = datetime.utcnow()

    result = await db.companies.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")

    return {"message": "Company updated successfully"}


# 🔴 Delete company (also delete linked user)
@router.delete("/{company_id}")
async def delete_company(company_id: str, user=Depends(require_roles("superadmin"))):

    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Delete company entry
    await db.companies.delete_one({"_id": ObjectId(company_id)})

    # Delete linked user
    await db.users.delete_one({"_id": ObjectId(company["user_id"])})

    return {"message": "Company and linked user deleted successfully"}
