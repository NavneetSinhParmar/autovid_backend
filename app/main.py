from fastapi import FastAPI
from app.routes import auth, company, customer, gallery, video_task

app = FastAPI(title="Video Automation API")

# Routers
app.include_router(auth.router)
app.include_router(company.router)
app.include_router(customer.router)
app.include_router(gallery.router)
app.include_router(video_task.router)

@app.get("/")
def root():
    return {"message": "Video Automation Backend Running!"}
