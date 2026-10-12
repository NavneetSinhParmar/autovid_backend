"""Single-host process limits. All services must share the same lock directory.

Linux flock descriptors are inherited by FFmpeg: locks survive parent death until
the child exits. Do not unlink lock files while any service/child is running.
This is deliberately not an expiring distributed lease.
"""
import contextvars
import functools
import os
import re
import time
from pathlib import Path

from app.core.settings import settings

job_lock_fd = contextvars.ContextVar("job_lock_fd", default=None)
render_slot_fd = contextvars.ContextVar("render_slot_fd", default=None)


class CapacityUnavailable(RuntimeError):
    pass


class FileLock:
    def __init__(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise ValueError("Invalid lock name")
        root = Path(os.getenv("RENDER_LOCK_DIR", "./.render_locks")).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / (name + ".lock")
        self.fd = None

    def acquire(self, blocking=False):
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            else:
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def close(self):
        if self.fd is not None:
            # Closing, rather than LOCK_UN, preserves an inherited child's lock.
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        # Windows LK_LOCK retries at one-second intervals. Avoid that latency
        # for short admission critical sections while preserving OS exclusion.
        deadline = time.monotonic() + 10
        while not self.acquire():
            if time.monotonic() >= deadline:
                raise CapacityUnavailable("Lock unavailable")
            time.sleep(0.01)
        return self

    def __exit__(self, *args):
        self.close()


def available_memory_mb():
    import psutil
    available = psutil.virtual_memory().available
    # Account for container/cgroup v2 and common v1 limits, when present.
    for limit_path, used_path in [
        ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),
    ]:
        try:
            limit = int(Path(limit_path).read_text().strip())
            used = int(Path(used_path).read_text().strip())
            available = min(available, max(0, limit - used))
        except (OSError, ValueError):
            pass
    return available / (1024 * 1024)


def acquire_render_slot():
    # Serialize memory admission and slot acquisition across worker processes.
    with FileLock("capacity_admission"):
        free = []
        occupied = 0
        for index in range(settings.max_concurrent_video_renders):
            lock = FileLock(f"ffmpeg_{index}")
            if lock.acquire():
                free.append(lock)
            else:
                occupied += 1
        try:
            required = settings.min_free_memory_mb + settings.estimated_render_memory_mb * (occupied + 1)
            if not free:
                raise CapacityUnavailable("Waiting for an available FFmpeg render slot")
            available = available_memory_mb()
            if available < required:
                raise CapacityUnavailable(f"Waiting for RAM: {available:.0f} MB available; {required:.0f} MB required")
            return free.pop(0)
        finally:
            for lock in free:
                lock.close()


def isolated_job(reserve_ffmpeg=False):
    """Acquire before Mongo claim; duplicates never share output/temp paths."""
    def decorate(function):
        @functools.wraps(function)
        def wrapped(task, job_id):
            lock = FileLock("job_" + job_id)
            if not lock.acquire():
                # A TTS stage can publish the next stage before releasing its lock.
                # Retry rather than dropping that delivery; no duplicate body runs.
                raise task.retry(exc=CapacityUnavailable("Job execution is still locked"), countdown=5, max_retries=None)
            slot = None
            token_job = job_lock_fd.set(lock.fd)
            token_slot = None
            try:
                if reserve_ffmpeg:
                    slot = acquire_render_slot()
                    token_slot = render_slot_fd.set(slot.fd)
                return function(task, job_id)
            except CapacityUnavailable as exc:
                from app.services.sync_db import sync_db
                reason = str(exc)
                result = sync_db.render_jobs.update_one(
                    {"job_id": job_id, "status": "QUEUED", "waiting_reason": {"$ne": reason}},
                    {"$set": {"waiting_reason": reason}},
                )
                if result.modified_count:
                    import logging
                    logging.getLogger(__name__).warning("[RENDER WAIT] job_id=%s %s", job_id, reason)
                # No Mongo claim yet and no render failure: don't spend retries.
                raise task.retry(exc=exc, countdown=5, max_retries=None)
            finally:
                if token_slot is not None:
                    render_slot_fd.reset(token_slot)
                job_lock_fd.reset(token_job)
                if slot:
                    slot.close()
                lock.close()
        return wrapped
    return decorate
