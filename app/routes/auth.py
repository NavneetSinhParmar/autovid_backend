from fastapi import APIRouter, HTTPException, Depends
from app.models.user_model import UserCreate, UserOut
from app.utils.auth import hash_password, verify_password, create_access_token, require_roles
from app.utils.auth import blacklist_token, oauth2_scheme, get_current_user,validate_role

from app.db.connection import db
from bson import ObjectId
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
from app.core.rate_limit import rate_limit
from app.core.settings import settings
from app.core.tenancy import object_id
from app.models.api_model import PasswordChangeRequest


router = APIRouter(prefix="/auth", tags=["Authentication"])

class ResetPasswordRequest(BaseModel):
    user_id: str | None = None
    old_password: str | None = None
    new_password: str = Field(min_length=10, max_length=72)


class PublicRegistrationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(min_length=10, max_length=72)
    role: str = "customer"


class LoginRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    password: str


@router.post("/register")
async def register_user(
    data: PublicRegistrationRequest,
    _=Depends(rate_limit("auth-register", 10, authenticated=False)),
):
    # 1️⃣ Extract required fields
    username = data.username.strip()
    email = str(data.email).lower()
    password = data.password
    role = data.role.lower()

    # 2️⃣ Validate role
    if role != "customer":
        raise HTTPException(status_code=403, detail="Public registration can only create customer accounts")

    # 3️⃣ Check if already exists
    if await db.users.find_one({"username": username}):
        raise HTTPException(status_code=400, detail="Username already exists")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already exists")

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
async def common_login(
    data: LoginRequest,
    _=Depends(rate_limit("auth-login", 20, authenticated=False)),
):
    username_or_email = data.username or (str(data.email).lower() if data.email else None)
    password = data.password

    if not username_or_email or not password:
        raise HTTPException(status_code=400, detail="Username/Email and password required")

    # 🔍 Find user by username OR email
    matches = await db.users.find({
        "$or": [
            {"username": username_or_email},
            {"email": username_or_email}
        ]
    }).limit(2).to_list(2)

    if len(matches) > 1:
        raise HTTPException(status_code=409, detail={
            "code": "AMBIGUOUS_ACCOUNT",
            "message": "Duplicate login records require administrator review",
        })
    user = matches[0] if matches else None

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # 🔐 Password verify
    if not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # 🎭 User role
    role = user.get("role", "customer")

    # 🔑 Create JWT
    token = create_access_token({"sub": str(user["_id"]), "role": role})

    # 🎯 Return minimal response
    return {
        "access_token": token,
        "role": role
    }

@router.post("/logout")
async def logout_user(token: str = Depends(oauth2_scheme)):
    blacklist_token(token)
    return {"message": "Successfully logged out!"}

@router.get("/profile")
async def get_profile(user=Depends(get_current_user)):

    role = user.get("role")
    user_id = str(user["_id"])    # convert to string for company / customer lookups
    if role == "superadmin":
        return {
            "role": "superadmin",
            "username": user["username"],
            "email": user["email"]
        }

    elif role == "company":
        company = await db.companies.find_one({"user_id": user_id})
        if not company:
            raise HTTPException(status_code=404, detail="Company profile not found")
        company["id"] = str(company["_id"])

        # Fix logo path before returning
        if company.get("logo_url"):
            company["logo_url"] = f"./media/{company['logo_url']}"

        return {
            "role": "company",
            "id": company["id"],
            "company_name": company["company_name"],
            "email": user["email"],
            "mobile": company["mobile"],
            "status": company["status"],
            "logo_url": company.get("logo_url"),
            "visibility": company.get("visibility"),
            "description": company.get("description"),
        }

    elif role == "customer":
        customer = await db.customers.find_one({"user_id": user_id})
        if customer:
            customer["id"] = str(customer["_id"])
            return {
                "role": "customer",
                "id": customer["id"],
                "full_name": customer["full_name"],
                "email": user["email"],
                "city": customer.get("city"),
                "phone_number": customer.get("phone_number"),
                "linked_company_id": customer.get("linked_company_id")
            }
        raise HTTPException(status_code=404, detail="Customer profile not found")

    raise HTTPException(status_code=404, detail="User not found")

@router.patch("/forgot-password")
async def change_user_password(data: PasswordChangeRequest, user=Depends(require_roles("superadmin"))):

    user_id = data.user_id
    new_password = data.new_password

    if not user_id or not new_password:
        raise HTTPException(status_code=400, detail="user_id and new_password required")

    # Check target user exists
    target_user = await db.users.find_one({"_id": object_id(user_id, "user_id")})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update password
    result = await db.users.update_one(
        {"_id": object_id(user_id, "user_id")},
        {"$set": {"password": hash_password(new_password)}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Password update failed")

    return {"message": "Password updated successfully", "user_id": user_id}

@router.patch("/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    current_user=Depends(get_current_user)
):
    # SUPERADMIN CAN RESET ANY USER
    if current_user["role"] == "superadmin":
        target_user_id = data.user_id or str(current_user["_id"])
    else:
        # normal user cannot enter user_id
        target_user_id = str(current_user["_id"])
        if data.user_id:
            raise HTTPException(403, "You are not allowed to reset other user's password")

    # Fetch user by target ID
    user = await db.users.find_one({"_id": object_id(target_user_id, "user_id")})
    if not user:
        raise HTTPException(404, "User not found")

    # Normal users must validate old password
    if current_user["role"] != "superadmin":
        if not data.old_password:
            raise HTTPException(400, "Old password is required")
        if not verify_password(data.old_password, user["password"]):
            raise HTTPException(400, "Old password is incorrect")

    # Update password
    new_hashed = hash_password(data.new_password)
    await db.users.update_one(
        {"_id": ObjectId(target_user_id)},
        {"$set": {"password": new_hashed}}
    )

    return {"message": "Password updated successfully"}
