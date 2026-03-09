from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, company, customer, admin, media, template, video_task, task, category, public, public_templates
from app.db.connection import db
from app.utils.auth import hash_password
import asyncio
from fastapi.staticfiles import StaticFiles


# ✅ Create app instance only once
app = FastAPI(title="AutoVid Backend")
app.mount("/media", StaticFiles(directory="media"), name="media")

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
