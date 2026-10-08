"""Read-only audit: python -m app.db.audit_duplicates."""
import asyncio
import json

from app.db.connection import client, db


async def audit() -> None:
    try:
        await db.command("ping")
        for field in ("email", "username"):
            pipeline = [
                {"$match": {field: {"$exists": True}}},
                {"$group": {"_id": "$" + field, "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}},
            ]
            groups = 0
            async for group in db.users.aggregate(pipeline):
                groups += 1
                ids = [str(row["_id"]) async for row in db.users.find(
                    {field: group["_id"]}, {"_id": 1}
                ).limit(20)]
                print(json.dumps({"field": field, "count": group["count"], "sample_user_ids": ids}))
            print(f"users.{field}: {groups} duplicate groups")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(audit())
