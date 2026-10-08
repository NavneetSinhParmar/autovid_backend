import logging
import asyncio
import os
import time
import uuid
import mimetypes
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response
from bson import ObjectId

from app.core.settings import settings
from app.db.connection import db
from app.db.indexes import ensure_indexes
from app.routes import (
    admin, auth, campaign, category, company, customer, media, public, public_templates,
    monitoring, render_jobs, task, template, video_task, voise_over,
)
from app.utils.auth import hash_password
from app.utils.auth import get_optional_current_user
from app.services.storage import get_media_abs_path

logger = logging.getLogger(__name__)


async def bootstrap_superadmin() -> None:
    email = os.getenv("BOOTSTRAP_SUPERADMIN_EMAIL")
    password = os.getenv("BOOTSTRAP_SUPERADMIN_PASSWORD")
    if not email or not password or await db.users.find_one({"role": "superadmin"}):
        return
    await db.users.insert_one({
        "username": os.getenv("BOOTSTRAP_SUPERADMIN_USERNAME", "Super Admin"),
        "email": email.lower(),
        "password": hash_password(password),
        "role": "superadmin",
        "status": "active",
    })
    logger.warning("Initial superadmin account created from environment configuration")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_indexes()
    await bootstrap_superadmin()
    yield


app = FastAPI(title="AutoVid Backend", lifespan=lifespan)

media_dir = os.getenv("LOCAL_MEDIA_ROOT", "media")
os.makedirs(media_dir, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    if len(request_id) > 128 or not re.fullmatch(r"[A-Za-z0-9._-]+", request_id):
        request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {"code": "VALIDATION_ERROR", "message": "Request validation failed", "details": jsonable_encoder(exc.errors())},
            "request_id": getattr(request.state, "request_id", None),
            "timestamp": time.time(),
        },
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and exc.detail.get("code"):
        error = exc.detail
    else:
        error = {"code": "HTTP_ERROR", "message": str(exc.detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error, "request_id": getattr(request.state, "request_id", None), "timestamp": time.time()},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled request error request_id=%s", getattr(request.state, "request_id", None))
    return JSONResponse(
        status_code=500,
        content={
            "error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred"},
            "request_id": getattr(request.state, "request_id", None),
            "timestamp": time.time(),
        },
    )


for router in (
    auth.router, company.router, customer.router, admin.router, media.router, campaign.router,
    template.router, video_task.router, task.router, category.router, monitoring.router,
    public.router, public_templates.router, voise_over.router, render_jobs.router,
):
    app.include_router(router)


@app.api_route("/media/{media_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_media(media_path: str, request: Request, user=Depends(get_optional_current_user)):
    normalized = media_path.replace("\\", "/").strip("/")
    parts = normalized.split("/")
    if not normalized or parts[0] == "render_jobs":
        raise HTTPException(404, "Media not found")

    allowed = user is not None and user.get("role") == "superadmin"
    if user is not None and user.get("role") == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})
        allowed = bool(company and parts[0] in {str(company["_id"]), str(company.get("user_id"))})

    if not allowed and len(parts) >= 3 and parts[1] == "templates" and ObjectId.is_valid(parts[2]):
        public_template = await db.templates.find_one({
            "_id": ObjectId(parts[2]), "company_id": parts[0],
            "public": True, "status": "active",
        }, {"_id": 1})
        allowed = public_template is not None

    if not allowed:
        from app.services.public_media import references_media
        templates = db.templates.find(
            {"company_id": parts[0], "public": True, "status": "active"},
            {"preview_image_url": 1, "base_image_url": 1, "base_video_url": 1,
             "base_audio_url": 1, "template_json": 1},
        )
        async for template in templates:
            if references_media(template, normalized):
                allowed = True
                break

    if not allowed:
        raise HTTPException(404, "Media not found")
    try:
        path = get_media_abs_path(normalized)
    except ValueError:
        raise HTTPException(404, "Media not found")
    if not os.path.isfile(path):
        raise HTTPException(404, "Media not found")
    stat = await asyncio.to_thread(os.stat, path)
    response = FileResponse(
        path, stat_result=stat,
        media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600", "Vary": "Cookie, Authorization"},
    )
    if request.headers.get("if-none-match") == response.headers.get("etag"):
        return Response(status_code=304, headers=dict(response.headers))
    return response


@app.get("/")
async def home():
    return {"message": "AutoVid Backend Running!"}


@app.get("/health")
async def health():
    await db.command("ping")
    return {"status": "ok"}
