from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RenderStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RenderJob(BaseModel):
    job_id: str
    company_id: str
    campaign_id: str | None = None
    customer_id: str | None = None
    template_id: str | None = None
    job_type: str
    status: RenderStatus = RenderStatus.QUEUED
    progress: int = Field(0, ge=0, le=100)
    priority: int = Field(0, ge=-10, le=10)
    retry_count: int = 0
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    render_duration: float | None = None
    output_url: str | None = None
    error: dict[str, Any] | None = None
    error_code: str | None = None
