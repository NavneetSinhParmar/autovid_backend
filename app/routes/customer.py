from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
from app.db.connection import db
from app.utils.auth import require_roles, hash_password

router = APIRouter(prefix="/customer", tags=["Customer Management"])


# 🟢 CREATE CUSTOMER (Admin or Company)
@router.post("/")
async def create_customer(data: dict, user=Depends(require_roles("superadmin", "company"))):
    print("This is for cistomer rellated APIs debugging only")
    # Check duplicate username / email
    if await db.users.find_one({"username": data["username"]}):
        raise HTTPException(status_code=400, detail="Username already exists")

    if await db.users.find_one({"email": data["email"]}):
        raise HTTPException(status_code=400, detail="Email already exists")

    # ---- STEP 1: Create USER entry ----
    user_doc = {
        "username": data["username"],
        "email": data["email"],
        "password": hash_password(data["password"]),
        "role": "customer",
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    user_result = await db.users.insert_one(user_doc)
    user_id = str(user_result.inserted_id)

    # ---- STEP 2: Create CUSTOMER entry ----
    customer_doc = {
        "customer_company_name": data.get("customer_company_name"),
        "full_name": data["full_name"],
        "logo_url": data.get("logo_url"),
        "city": data.get("city"),
        "phone_number": data.get("phone_number"),
        "telephone_number": data.get("telephone_number"),
        "address": data.get("address"),

        # relationships
        "linked_company_id": data.get("linked_company_id"),
        "user_id": user_id,

        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    customer_result = await db.customers.insert_one(customer_doc)

    return {
        "message": "Customer created successfully",
        "customer_id": str(customer_result.inserted_id),
        "user_id": user_id
    }


# 🔵 LIST CUSTOMERS (WITH JOIN: USER + COMPANY)
@router.get("/")
async def list_customers(user=Depends(require_roles("superadmin", "company"))):

    pipeline = [
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
                "as": "company"
            }
        },
        {"$unwind": {"path": "$company", "preserveNullAndEmptyArrays": True}},
    ]

    customers = []

    async for doc in db.customers.aggregate(pipeline):
        # Format IDs
        doc["id"] = str(doc["_id"])
        del doc["_id"]

        doc["user"]["id"] = str(doc["user"]["_id"])
        del doc["user"]["_id"]
        del doc["user"]["password"]  # never return password

        if doc.get("company"):
            doc["company"]["id"] = str(doc["company"]["_id"])
            del doc["company"]["_id"]

        customers.append(doc)

    return customers


# 🟠 GET SINGLE CUSTOMER (JOIN: USER + COMPANY)
@router.get("/{customer_id}")
async def get_customer(customer_id: str, user=Depends(require_roles("superadmin", "company"))):

    pipeline = [
        {"$match": {"_id": ObjectId(customer_id)}},
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
                "as": "company"
            }
        },
        {"$unwind": {"path": "$company", "preserveNullAndEmptyArrays": True}},
    ]

    result = await db.customers.aggregate(pipeline).to_list(1)
    if not result:
        raise HTTPException(status_code=404, detail="Customer not found")

    doc = result[0]

    doc["id"] = str(doc["_id"])
    del doc["_id"]

    doc["user"]["id"] = str(doc["user"]["_id"])
    del doc["user"]["_id"]
    del doc["user"]["password"]

    if doc.get("company"):
        doc["company"]["id"] = str(doc["company"]["_id"])
        del doc["company"]["_id"]

    return doc


# 🟣 UPDATE CUSTOMER
@router.patch("/{customer_id}")
async def update_customer(customer_id: str, data: dict, user=Depends(require_roles("superadmin", "company"))):

    data["updated_at"] = datetime.utcnow()

    # Prevent changing user_id directly
    if "user_id" in data:
        del data["user_id"]

    result = await db.customers.update_one(
        {"_id": ObjectId(customer_id)},
        {"$set": data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Customer not found")

    return {"message": "Customer updated successfully"}


# 🔴 DELETE CUSTOMER (ALSO DELETE LINKED USER)
@router.delete("/{customer_id}")
async def delete_customer(customer_id: str, user=Depends(require_roles("superadmin", "company"))):

    customer = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Delete customer
    await db.customers.delete_one({"_id": ObjectId(customer_id)})

    # Delete linked User
    await db.users.delete_one({"_id": ObjectId(customer["user_id"])})

    return {"message": "Customer and linked user deleted successfully"}
