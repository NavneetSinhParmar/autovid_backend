from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
from typing import Union, List, Dict, Any

from app.db.connection import db
from app.utils.auth import require_roles, hash_password
from app.models.customer_model import CustomerCreate, CustomerOut
from fastapi import Request, UploadFile, File, Form

router = APIRouter(prefix="/customer", tags=["Customer Management"])

# --------------------------------------------------------
# 🟢 Helper: Convert string → ObjectId with safe handling
# --------------------------------------------------------
def to_oid(value: str):
    try:
        return ObjectId(value)
    except:
        raise HTTPException(status_code=400, detail=f"Invalid ObjectId: {value}")

# --------------------------------------------------------
# 🟢 Helper: Validate and Create Customer Document
# --------------------------------------------------------
async def create_single_customer(data: Dict[str, Any], user: Dict):

    # 1️⃣ If logged user is COMPANY → auto set linked_company_id
    if user["role"] == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})

        if not company:
            raise HTTPException(status_code=404,
                                detail="Company record not found for this user")
        
        data["linked_company_id"] = str(company["_id"])  # override automatically

    # 2️⃣ SUPERADMIN must give linked_company_id
    elif user["role"] == "superadmin":
        if "linked_company_id" not in data:
            raise HTTPException(status_code=400,
                                detail="linked_company_id is required for superadmin")

    # 3️⃣ Check Duplicate User
    if await db.users.find_one({"username": data["username"]}):
        raise HTTPException(status_code=400, detail="Username already exists")

    if await db.users.find_one({"email": data["email"]}):
        raise HTTPException(status_code=400, detail="Email already exists")

    # 4️⃣ Create User Record
    user_doc = {
        "username": data["username"],
        "email": data["email"],
        "password": hash_password(data["password"]),
        "role": "customer",
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    inserted_user = await db.users.insert_one(user_doc)
    user_id = str(inserted_user.inserted_id)

    # 5️⃣ Prepare Customer Record
    customer_doc = {
        "customer_company_name": data.get("customer_company_name"),
        "full_name": data["full_name"],
        "logo_url": data.get("logo_url"),
        "city": data.get("city"),
        "phone_number": data.get("phone_number"),
        "telephone_number": data.get("telephone_number"),
        "address": data.get("address"),

        "linked_company_id": to_oid(data["linked_company_id"]),
        "user_id": to_oid(user_id),

        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    inserted = await db.customers.insert_one(customer_doc)

    return {
        "message": "Customer created successfully",
        "customer_id": str(inserted.inserted_id),
        "user_id": user_id,
    }

# --------------------------------------------------------
# 🟢 CREATE CUSTOMER (Single / Bulk)
# --------------------------------------------------------
@router.post("/")
async def create_customer_handler(
    request: Request,
    logo_file: UploadFile = File(None),  # optional
    user=Depends(require_roles("superadmin", "company")),
):
    content_type = request.headers.get("content-type", "")

    # ----------------------------------
    # 🔵 CASE 1: JSON → Bulk or Single
    # ----------------------------------
    if content_type.startswith("application/json"):
        data = await request.json()

        # 🔹 Bulk
        if isinstance(data, list):
            if not data:
                raise HTTPException(status_code=400, detail="Input list cannot be empty")

            results = []
            for item in data:
                try:
                    res = await create_single_customer(item, user)
                    results.append({"success": True, "data": res})
                except HTTPException as e:
                    results.append({"success": False, "error": e.detail, "data": item})

            return {
                "message": "Bulk creation completed",
                "total": len(data),
                "results": results,
            }

        # 🔹 Single JSON (no file)
        return await create_single_customer(data, user)

    # ----------------------------------
    # 🟢 CASE 2: FORM-DATA → Single + File
    # ----------------------------------
    elif content_type.startswith("multipart/form-data"):
        form = await request.form()

        # Convert form-data → dict (NO bytes issue)
        data = dict(form)

        # Remove file object from dict
        data.pop("logo_file", None)

        # Save logo if provided
        if logo_file:
            from app.services.storage import save_upload_file
            path, _ = await save_upload_file(logo_file, data["username"])
            data["logo_url"] = path

        return await create_single_customer(data, user)

    else:
        raise HTTPException(status_code=415, detail="Unsupported Content-Type")

# @router.post("/")
# async def create_customer_handler(
#     data: Union[Dict, List[Dict]],
#     user=Depends(require_roles("superadmin", "company"))
# ):

#     # 🔵 Bulk Creation
#     if isinstance(data, list):
#         if not data:
#             raise HTTPException(status_code=400, detail="Input list cannot be empty")

#         results = []
#         for item in data:
#             try:
#                 result = await create_single_customer(item, user)
#                 results.append({"success": True, "data": result})
#             except HTTPException as e:
#                 results.append({"success": False, "error": e.detail, "data": item})

#         return {
#             "message": "Bulk creation completed",
#             "total": len(data),
#             "results": results,
#         }

#     else:
#         # 🔵 Single Creation
#         print("Single customer creation")
#         return await create_single_customer(data, user)

# --------------------------------------------------------
# 🔵 LIST CUSTOMERS WITH USER + COMPANY JOIN
# --------------------------------------------------------
@router.get("/")
async def list_customers(user=Depends(require_roles("superadmin", "company"))):

    pipeline = [
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user",
            }
        },
        {"$unwind": "$user"},
        {
            "$lookup": {
                "from": "companies",
                "localField": "linked_company_id",
                "foreignField": "_id",
                "as": "company",
            }
        },
        {"$unwind": {"path": "$company", "preserveNullAndEmptyArrays": True}},
    ]

    data = []
    async for doc in db.customers.aggregate(pipeline):

        # Convert ObjectIds
        doc["id"] = str(doc.pop("_id"))
        doc["user_id"] = str(doc["user_id"])
        doc["linked_company_id"] = str(doc["linked_company_id"])

        doc["user"]["id"] = str(doc["user"].pop("_id"))
        doc["user"].pop("password")

        if doc.get("company"):
            doc["company"]["id"] = str(doc["company"].pop("_id"))

        data.append(doc)

    return data

# --------------------------------------------------------
# 🔵 GET SINGLE CUSTOMER
# --------------------------------------------------------
@router.get("/{customer_id}")
async def get_customer(customer_id: str, user=Depends(require_roles("superadmin", "company"))):

    pipeline = [
        {"$match": {"_id": to_oid(customer_id)}},
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user"
            }
        },
        {"$unwind": "$user"},
        {
            "$lookup": {
                "from": "companies",
                "localField": "linked_company_id",
                "foreignField": "_id",
                "as": "company",
            }
        },
        {"$unwind": {"path": "$company", "preserveNullAndEmptyArrays": True}},
    ]

    result = await db.customers.aggregate(pipeline).to_list(1)
    if not result:
        raise HTTPException(status_code=404, detail="Customer not found")

    doc = result[0]

    doc["id"] = str(doc.pop("_id"))
    doc["user_id"] = str(doc["user_id"])
    doc["linked_company_id"] = str(doc["linked_company_id"])

    doc["user"]["id"] = str(doc["user"].pop("_id"))
    doc["user"].pop("password")

    if doc.get("company"):
        doc["company"]["id"] = str(doc["company"].pop("_id"))

    return doc

# --------------------------------------------------------
# 🟠 UPDATE CUSTOMER
# --------------------------------------------------------
@router.patch("/{customer_id}")
async def update_customer(customer_id: str, data: Dict, 
                          user=Depends(require_roles("superadmin", "company"))):

    data["updated_at"] = datetime.utcnow()

    # Can't manually change user_id
    data.pop("user_id", None)

    result = await db.customers.update_one(
        {"_id": to_oid(customer_id)},
        {"$set": data},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Customer not found")

    return {"message": "Customer updated successfully"}

# --------------------------------------------------------
# 🔴 DELETE CUSTOMER + LINKED USER
# --------------------------------------------------------
@router.delete("/{customer_id}")
async def delete_customer(customer_id: str, user=Depends(require_roles("superadmin", "company"))):

    customer = await db.customers.find_one({"_id": to_oid(customer_id)})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    await db.customers.delete_one({"_id": to_oid(customer_id)})
    await db.users.delete_one({"_id": customer["user_id"]})

    return {"message": "Customer and linked user deleted successfully"}
