from fastapi import FastAPI
from app.routes import auth, company, customer, admin
from app.db.connection import db
from app.utils.auth import hash_password
import asyncio

app = FastAPI(title="AutoVid Backend")

app.include_router(auth.router)
app.include_router(company.router)
app.include_router(customer.router)
app.include_router(admin.router) 

@app.get("/")
async def home():
    return {"message": "AutoVid Backend Running!"}


# 🔹 SuperAdmin Seeder Function
async def create_super_admin():
    existing = await db.users.find_one({"role": "superadmin"})
    if not existing:
        superadmin_data = {
            "name": "Super Admin",
            "email": "superadmin@autovid.com",
            "password": hash_password("Admin@123"),  # default password
            "role": "superadmin"
        }
        await db.users.insert_one(superadmin_data)
        print("✅ SuperAdmin created: superadmin@autovid.com / Admin@123")
    else:
        print("ℹ️ SuperAdmin already exists.")


@app.on_event("startup")
async def startup_event():
    await create_super_admin()  
    print("🚀 Application startup complete.")
