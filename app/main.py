from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, company, customer, admin, media, template, video_task, task, category, public, public_templates, voise_over
from app.db.connection import db
from app.utils.auth import hash_password
import asyncio
from fastapi.staticfiles import StaticFiles
import os


# ✅ Create app instance only once
app = FastAPI(title="AutoVid Backend")

# Ensure `media` directory exists before mounting StaticFiles to avoid startup crashes
media_dir = "media"
if not os.path.isdir(media_dir):
    try:
        os.makedirs(media_dir, exist_ok=True)
        print(f"Created missing directory: {media_dir}")
    except Exception as e:
        print(f"Warning: could not create media directory '{media_dir}': {e}")

app.mount("/media", StaticFiles(directory=media_dir), name="media")

# ✅ CORS setup
origins = [
    "http://localhost:3000",
    "https://videoedittool-puce.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],          # ✅ allow all methods
    allow_headers=["*"], 
)

# ✅ Include routers
app.include_router(auth.router)
app.include_router(company.router)
app.include_router(customer.router)
app.include_router(admin.router)
app.include_router(media.router)
app.include_router(template.router)
app.include_router(video_task.router)
app.include_router(task.router)
app.include_router(category.router)
app.include_router(public.router)
app.include_router(public_templates.router)
app.include_router(voise_over.router)

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
# main.py
@app.on_event("startup")
async def startup_event():
    await create_super_admin()
    print("🚀 Application startup complete.")
