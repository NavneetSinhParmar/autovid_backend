from app.db.connection import db
from pymongo.errors import DuplicateKeyError
import logging
import os
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def allow_local_legacy_indexes() -> bool:
    return (
        os.getenv("APP_ENV") == "development"
        and os.getenv("ALLOW_LOCAL_LEGACY_USER_INDEXES", "false").lower() == "true"
        and urlsplit(os.getenv("MONGO_URL", "")).hostname in {"localhost", "127.0.0.1", "::1"}
    )


async def ensure_user_unique_index(field: str) -> None:
    try:
        await db.users.create_index(field, unique=True, sparse=True, name=f"users_{field}_unique")
    except DuplicateKeyError:
        if allow_local_legacy_indexes():
            logger.warning(
                "LOCAL DEVELOPMENT: users.%s unique index deferred due to legacy duplicates. "
                "Run python -m app.db.audit_duplicates and resolve before production.", field,
            )
            return
        raise RuntimeError(
            f"MongoDB connected, but users.{field} contains duplicate values. "
            "Run `python -m app.db.audit_duplicates` to identify affected user IDs. "
            "Resolve duplicate accounts after reviewing ownership and backups, then restart. "
            "Environment changes cannot fix duplicate records; no records were deleted."
        ) from None


async def ensure_indexes() -> None:
    # Canonical tenant identifiers are strings. Read paths remain compatible
    # with ObjectIds while this startup migration normalizes legacy rows.
    await db.customers.update_many(
        {"linked_company_id": {"$type": "objectId"}},
        [{"$set": {"linked_company_id": {"$toString": "$linked_company_id"}}}],
    )
    await ensure_user_unique_index("email")
    await ensure_user_unique_index("username")
    await db.companies.create_index("user_id", unique=True, name="companies_user_id_unique")
    await db.customers.create_index(
        [("linked_company_id", 1), ("distributed_id", 1)], unique=True,
        partialFilterExpression={"distributed_id": {"$type": "string"}},
        name="customers_company_distributed_unique",
    )
    await db.customers.create_index([("linked_company_id", 1), ("created_at", -1)], name="customers_company_created")
    await db.categories.create_index([("company_id", 1), ("status", 1), ("created_at", -1)], name="categories_company_status_created")
    await db.templates.create_index([("company_id", 1), ("status", 1), ("created_at", -1)], name="templates_company_status_created")
    await db.media.create_index([("company_id", 1), ("created_at", -1)], name="media_company_created")
    await db.media.create_index([("company_id", 1), ("file_type", 1), ("created_at", -1)], name="media_company_type_created")
    await db.render_jobs.create_index("job_id", unique=True, name="render_jobs_job_id_unique")
    await db.render_jobs.create_index(
        [("company_id", 1), ("idempotency_key", 1)], unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
        name="render_jobs_idempotency_unique",
    )
    await db.render_jobs.create_index([("company_id", 1), ("status", 1), ("created_at", -1)], name="render_jobs_company_status_created")
    await db.render_jobs.create_index([("campaign_id", 1), ("status", 1)], name="render_jobs_campaign_status")
    await db.render_jobs.create_index([("company_id", 1), ("customer_id", 1), ("created_at", -1)], name="render_jobs_company_customer_created")
    await db.render_jobs.create_index([("company_id", 1), ("template_id", 1), ("created_at", -1)], name="render_jobs_company_template_created")
    await db.campaigns.create_index([("company_id", 1), ("created_at", -1)], name="campaigns_company_created")
    await db.campaigns.create_index([("company_id", 1), ("status", 1)], name="campaigns_company_status")
    await db.campaigns.create_index(
        [("company_id", 1), ("idempotency_key", 1)], unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
        name="campaigns_idempotency_unique",
    )
    await db.video_tasks.create_index([("company_id", 1), ("status", 1), ("created_at", -1)], name="video_tasks_company_status_created")
