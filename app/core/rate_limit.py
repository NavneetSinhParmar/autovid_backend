import asyncio
import os
import time
import logging
from collections import defaultdict, deque

from fastapi import Depends, Request

from app.core.errors import AppError
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window: int = 60) -> None:
        now = time.monotonic()
        async with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                raise AppError(429, "RATE_LIMIT_EXCEEDED", "Too many requests. Please retry later.")
            hits.append(now)


limiter = SlidingWindowLimiter()
_redis_client = None


async def _distributed_check(key: str, limit: int, window: int = 60) -> None:
    global _redis_client
    queue_backend = os.getenv(
        "RENDER_QUEUE_BACKEND", "memory" if os.getenv("APP_ENV") == "development" else "celery"
    ).lower()
    if queue_backend == "memory":
        await limiter.check(key, limit, window)
        return
    try:
        if _redis_client is None:
            from redis.asyncio import Redis
            _redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        bucket = int(time.time()) // window
        redis_key = f"rate-limit:{key}:{bucket}"
        count = await _redis_client.incr(redis_key)
        if count == 1:
            await _redis_client.expire(redis_key, window + 1)
        if count > limit:
            raise AppError(429, "RATE_LIMIT_EXCEEDED", "Too many requests. Please retry later.")
    except AppError:
        raise
    except Exception:
        logger.warning("Redis rate limiter unavailable; using process-local fallback")
        await limiter.check(key, limit, window)


def rate_limit(scope: str, limit: int, authenticated: bool = True):
    async def dependency(request: Request, user=Depends(get_current_user) if authenticated else None):
        identity = str(user["_id"]) if user else (request.client.host if request.client else "unknown")
        await _distributed_check(f"{scope}:{identity}", limit)
        return user
    return dependency
