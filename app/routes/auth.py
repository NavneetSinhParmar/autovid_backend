from fastapi import APIRouter, HTTPException, Depends
from app.models.user_model import UserCreate, UserOut
from app.utils.auth import hash_password, verify_password, create_access_token, require_roles

from app.db.connection import db
from bson import ObjectId

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserOut)
async def register_user(user: UserCreate):
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    hashed_pw = hash_password(user.password)
    user_dict = user.dict()
    user_dict["password"] = hashed_pw
    user_dict["status"] = "active"
    result = await db.users.insert_one(user_dict)

    return {"id": str(result.inserted_id), "name": user.name, "email": user.email, "role": user.role}


@router.post("/login")
async def login_user(payload: dict):
    user = await db.users.find_one({"email": payload["email"]})
    print("user Password is",payload["password"])
    print("request body Password is",user["password"])
    if not user or not verify_password(payload["password"], user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="Account is inactive. Please contact SuperAdmin.")

    token = create_access_token({"sub": str(user["_id"]), "role": user["role"]})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
async def get_me(user=Depends(require_roles("superadmin","admin","customer"))):
    user["_id"] = str(user["_id"])
    del user["password"]
    return user
