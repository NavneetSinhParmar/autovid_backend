import os

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse

from app.services.render_queue import get_persisted_render_job

router = APIRouter(prefix="/render-jobs", tags=["Render Jobs"])


@router.get("/{job_id}")
async def render_job_status(job_id: str):
    job = await get_persisted_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")
    return jsonable_encoder(job)


@router.get("/{job_id}/download")
async def render_job_download(job_id: str):
    job = await get_persisted_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")
    if job["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"Render job is {job['status']}")

    output_path = job.get("output_path")
    if not output_path or not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Rendered output file not found")

    media_type = "image/jpeg" if output_path.lower().endswith((".jpg", ".jpeg")) else "video/mp4"
    return FileResponse(path=output_path, media_type=media_type, filename=os.path.basename(output_path))
