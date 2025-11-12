from fastapi import APIRouter, HTTPException, Depends
from app.models.user_model import UserCreate, UserOut
from app.utils.auth import hash_password, verify_password, create_access_token, require_roles
from app.utils.auth import blacklist_token, oauth2_scheme, get_current_user,validate_role

from app.db.connection import db
from bson import ObjectId
from datetime import datetime


router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register")
async def register_user(data: dict):
    # 1️⃣ Extract required fields
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    role = data.get("role")

    # 2️⃣ Validate role
    validate_role(role)

    # 3️⃣ Check if already exists
    if await db.users.find_one({"username": username}):
        raise HTTPException(status_code=400, detail="Username already exists")

    # 4️⃣ Create new user
    user_doc = {
        "username": username,
        "email": email,
        "password": hash_password(password),
        "role": role,
        "status": "active",
        "created_at": datetime.utcnow(),
    }
    await db.users.insert_one(user_doc)

    return {"message": "User registered successfully", "role": role}

@router.post("/login")
async def common_login(data: dict):
    print("Login data received:", data)

    username_or_email = data.get("username") or data.get("email")
    password = data.get("password")

    if not username_or_email or not password:
        raise HTTPException(status_code=400, detail="Username/Email and password required")

    print("Attempting login for:", username_or_email)

    # 🔍 Try SuperAdmin
    user = await db.users.find_one({
        "$or": [
            {"name": username_or_email},
            {"email": username_or_email}
        ]
    })

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user["role"] == "superadmin" and verify_password(password, user["password"]):
        token = create_access_token({"sub": str(user["_id"]), "role": "superadmin"})
        return {"access_token": token, "role": "superadmin"}

    # 2️⃣ Try Company
    company = await db.companies.find_one({"username": username_or_email})
    if company and verify_password(password, company["password"]):
        if company.get("status") != "active":
            raise HTTPException(status_code=403, detail="Company account inactive")
        token = create_access_token({"sub": str(company["_id"]), "role": "company"})
        return {"access_token": token, "role": "company"}

    # 3️⃣ Try Customer
    customer = await db.customers.find_one({"username": username_or_email})
    if customer and verify_password(password, customer["password"]):
        if customer.get("status") != "active":
            raise HTTPException(status_code=403, detail="Customer account inactive")
        token = create_access_token({"sub": str(customer["_id"]), "role": "customer"})
        return {"access_token": token, "role": "customer"}

    # ❌ Invalid
    raise HTTPException(status_code=401, detail="Invalid username or password")

@router.post("/logout")
async def logout_user(token: str = Depends(oauth2_scheme)):
    blacklist_token(token)
    return {"message": "Successfully logged out!"}

@router.get("/profile")
async def get_profile(user=Depends(get_current_user)):
    # print("Fetching profile for user:", user)
    role = user.get("role")
    if role == "superadmin":
        return {
            "role": "superadmin",
            "username": user["name"],
            "email": user["email"]
        }

    elif role == "company":
        company = await db.companies.find_one({"_id": ObjectId(user["_id"])})
        if company:
            return {
                "role": "company",
                "company_name": company["company_name"],
                "email": company["email"],
                "mobile": company["mobile"],
                "status": company["status"]
            }

    elif role == "customer":
        customer = await db.customers.find_one({"_id": ObjectId(user["_id"])})
        if customer:
            return {
                "role": "customer",
                "name": customer["name"],
                "email": customer["email"],
                "company_id": customer["linked_company_id"]
            }

    raise HTTPException(status_code=404, detail="User not found")

