import os
import hashlib
import hmac
import mimetypes
import re
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse

from app.core.pagination import PaginationParams, page_result
from app.core.tenancy import company_id_for_user
from app.db.connection import db
from app.utils.auth import get_optional_current_user

router = APIRouter(prefix="/render-jobs", tags=["Render Jobs"])


async def _owned_job(job_id: str, user: dict | None, access_token: str | None = None) -> dict:
    job = await db.render_jobs.find_one({"job_id": job_id}, {"payload": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")
    job["id"] = str(job.pop("_id"))
    job["status"] = str(job.get("status") or "QUEUED").upper()
    token_hash = job.get("access_token_hash")
    has_capability = bool(access_token and token_hash and hmac.compare_digest(hashlib.sha256(access_token.encode()).hexdigest(), token_hash))
    if not user and not has_capability:
        raise HTTPException(status_code=401, detail="Authentication or a valid job access token is required")
    if user and user.get("role") != "superadmin":
        company_id = await company_id_for_user(user)
        if str(job.get("company_id")) != company_id:
            raise HTTPException(status_code=404, detail="Render job not found")
    job.pop("payload", None)
    job.pop("access_token_hash", None)
    return job


@router.get("")
async def list_render_jobs(
    pagination: PaginationParams = Depends(),
    status: str | None = None,
    campaign_id: str | None = None,
    job_type: str | None = None,
    user=Depends(get_optional_current_user),
):
    if not user or user.get("role") not in {"superadmin", "company"}:
        raise HTTPException(403, "Company access required")
    query: dict = {}
    if user.get("role") != "superadmin":
        query["company_id"] = await company_id_for_user(user)
    if status:
        query["status"] = status.upper()
    if campaign_id:
        query["campaign_id"] = campaign_id
    if job_type:
        query["job_type"] = job_type
    if pagination.search:
        query["$or"] = [
            {"job_id": {"$regex": re.escape(pagination.search), "$options": "i"}},
            {"template_id": pagination.search},
            {"customer_id": pagination.search},
        ]
    total = await db.render_jobs.count_documents(query)
    sort_field, sort_direction = pagination.sort({"created_at", "updated_at", "status", "progress", "render_duration"})
    docs = await db.render_jobs.find(query, {"payload": 0, "output_path": 0, "access_token_hash": 0}).sort(sort_field, sort_direction).skip(pagination.skip).limit(pagination.limit).to_list(pagination.limit)
    for doc in docs:
        doc["id"] = str(doc.pop("_id"))
    return jsonable_encoder(page_result(docs, total, pagination))


@router.get("/{job_id}")
async def render_job_status(job_id: str, request: Request, access_token: str | None = None,
                            wait_seconds: float = Query(0, ge=0, le=15), wait_for_progress: bool = False, user=Depends(get_optional_current_user)):
    job = await _owned_job(job_id, user, access_token)
    # Optional long poll: one HTTP request returns immediately on completion.
    # Authorization runs before waiting; ordinary callers keep the existing API.
    deadline = asyncio.get_running_loop().time() + wait_seconds
    initial_status = job["status"]
    initial_progress = float(job.get("progress") or 0)
    initial_reason = job.get("waiting_reason")
    while job["status"] in {"QUEUED", "PROCESSING"}:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0 or await request.is_disconnected():
            break
        await asyncio.sleep(min(0.2, remaining))
        latest = await db.render_jobs.find_one({"job_id": job_id, "company_id": job.get("company_id")}, {"payload": 0, "access_token_hash": 0, "output_path": 0})
        if not latest:
            raise HTTPException(404, "Render job not found")
        latest["id"] = str(latest.pop("_id"))
        latest["status"] = str(latest.get("status") or "QUEUED").upper()
        job = latest
        if wait_for_progress and (job["status"] != initial_status or float(job.get("progress") or 0) >= initial_progress + 5 or job.get("waiting_reason") != initial_reason):
            break
    job.pop("output_path", None)
    return jsonable_encoder(job)


@router.post("/{job_id}/cancel")
async def cancel_render_job(job_id: str, user=Depends(get_optional_current_user)):
    if not user or user.get("role") not in {"superadmin", "company"}:
        raise HTTPException(403, "Company access required")
    await _owned_job(job_id, user)
    result = await db.render_jobs.update_one(
        {"job_id": job_id, "status": "QUEUED"},
        {"$set": {"status": "CANCELLED", "progress": 0}},
    )
    if not result.modified_count:
        raise HTTPException(status_code=409, detail="Only queued jobs can be cancelled")
    return {"job_id": job_id, "status": "CANCELLED"}


@router.get("/{job_id}/download")
async def render_job_download(job_id: str, access_token: str | None = None, user=Depends(get_optional_current_user)):
    job = await _owned_job(job_id, user, access_token)
    if job["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"Render job is {job['status']}")
    output_path = job.get("output_path")
    if not output_path or not os.path.isfile(output_path):
        raise HTTPException(status_code=404, detail="Rendered output file not found")
    media_type = mimetypes.guess_type(output_path)[0] or "application/octet-stream"
    return FileResponse(path=output_path, media_type=media_type, filename=os.path.basename(output_path))
