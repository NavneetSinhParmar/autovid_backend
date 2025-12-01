from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, company, customer, admin, media
from app.db.connection import db
from app.utils.auth import hash_password
import asyncio
from fastapi.staticfiles import StaticFiles
import os

# ✅ Create app instance only once
app = FastAPI(title="AutoVid Backend")

os.makedirs("media_storage", exist_ok=True)
app.mount("/public/media", StaticFiles(directory="media_storage"), name="media_storage")

# ✅ CORS setup
origins = [
    "http://localhost:3000",  # React frontend
    "http://127.0.0.1:3000",
    "https://your-frontend-domain.com"  # Production domain
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,          # URLs allowed to access
    allow_credentials=True,         # Allow cookies, authorization headers
    allow_methods=["*"],            # Allow all HTTP methods
    allow_headers=["*"],            # Allow all headers
)

# ✅ Include routers
app.include_router(auth.router)
app.include_router(company.router)
app.include_router(customer.router)
app.include_router(admin.router)
app.include_router(media.router)

# ✅ Simple health check route
@app.get("/")
async def home():
    return {"message": "AutoVid Backend Running!"}

# ✅ Seeder function for superadmin
async def create_super_admin():
    existing = await db.users.find_one({"role": "superadmin"})
    if not existing:
        superadmin_data = {
            "username": "Super Admin",
            "email": "superadmin@autovid.com",
            "password": hash_password("Admin@123"),
            "role": "superadmin"
        }
        await db.users.insert_one(superadmin_data)
        print("✅ SuperAdmin created: superadmin@autovid.com / Admin@123")
    else:
        print("ℹ️ SuperAdmin already exists.")

# ✅ Run at startup
@app.on_event("startup")
async def startup_event():
    await create_super_admin()
    print("🚀 Application startup complete.")
