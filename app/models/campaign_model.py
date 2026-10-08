from datetime import datetime

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template_id: str
    customer_ids: list[str] = Field(default_factory=list, max_length=5000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)


class CampaignStatus:
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
