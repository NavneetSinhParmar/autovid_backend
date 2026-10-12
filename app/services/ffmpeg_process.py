"""Bounded FFmpeg runner with child cleanup and optional file-based progress."""
import os
import subprocess
import tempfile
import time
import logging
from pathlib import Path

from app.core.settings import settings
from app.services.render_resources import acquire_render_slot, job_lock_fd, render_slot_fd

logger = logging.getLogger(__name__)


def safe_command(cmd):
    # Avoid logging signed URLs, credentials, personalized text and filter graphs.
    result = []
    redact_next = False
    for value in cmd:
        value = str(value)
        if redact_next:
            result.append("<filter graph>")
            redact_next = False
        elif value.startswith(("http://", "https://", "redis://", "mongodb://", "mongodb+srv://")):
            result.append("<remote input>")
        else:
            result.append(value)
            redact_next = value in {"-filter_complex", "-vf", "-af", "-filter:v", "-filter:a"}
    import shlex
    return shlex.join(result)


def run_ffmpeg(cmd, **kwargs):
    slot = None
    progress_path = None
    if render_slot_fd.get() is None:
        slot = acquire_render_slot()
    try:
        cmd = list(cmd)
        inherited = [fd for fd in (job_lock_fd.get(), render_slot_fd.get(), slot.fd if slot else None) if fd is not None]
        if os.name == "posix":
            kwargs["pass_fds"] = tuple(inherited)
        timeout = kwargs.pop("timeout", settings.ffmpeg_timeout_seconds)
        if timeout is None:
            timeout = settings.ffmpeg_timeout_seconds
        check = kwargs.pop("check", False)
        capture = kwargs.pop("capture_output", False)
        if capture:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
        input_data = kwargs.pop("input", None)
        if input_data is not None:
            kwargs["stdin"] = subprocess.PIPE
        from app.services.render_queue import current_render_job_id
        job_id = current_render_job_id.get()
        duration = None
        if "-t" in cmd:
            duration = float(cmd[cmd.index("-t") + 1])
        if job_id and duration:
            handle, progress_path = tempfile.mkstemp(prefix="ffmpeg-progress-", suffix=".txt")
            os.close(handle)
            cmd[1:1] = ["-progress", progress_path, "-nostats"]
        deadline = time.monotonic() + timeout
        kind = "IMAGE" if "-frames:v" in cmd else "VIDEO" if "libx264" in cmd else "AUDIO"
        started = time.monotonic()
        last_progress = 0
        logger.info("[FFMPEG] START kind=%s job_id=%s timeout=%ss", kind, job_id or "-", timeout)
        logger.info("[FFMPEG] COMMAND %s", safe_command(cmd))
        with subprocess.Popen(cmd, **kwargs) as process:
            logger.info("[FFMPEG] RUNNING kind=%s job_id=%s pid=%s", kind, job_id or "-", process.pid)
            try:
                first = True
                while True:
                    try:
                        stdout, stderr = process.communicate(input=input_data if first else None, timeout=min(1, max(0.01, deadline - time.monotonic())))
                        break
                    except subprocess.TimeoutExpired:
                        first = False
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(cmd, timeout)
                        if progress_path:
                            progress = update_progress(job_id, progress_path, duration)
                            if progress is not None and progress >= last_progress + 10:
                                logger.info("[FFMPEG] PROGRESS job_id=%s pid=%s progress=%s%%", job_id, process.pid, progress)
                                last_progress = progress
                logger.log(logging.INFO if process.returncode == 0 else logging.ERROR,
                           "[FFMPEG] %s kind=%s job_id=%s pid=%s exit_code=%s elapsed=%.2fs",
                           "COMPLETED" if process.returncode == 0 else "FAILED", kind, job_id or "-", process.pid,
                           process.returncode, time.monotonic() - started)
                if check and process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)
                return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
            except BaseException as exc:
                if not isinstance(exc, subprocess.CalledProcessError):
                    logger.error("[FFMPEG] STOPPED kind=%s job_id=%s pid=%s reason=%s elapsed=%.2fs",
                                 kind, job_id or "-", process.pid, type(exc).__name__, time.monotonic() - started)
                # Only terminate this invocation; never kill unrelated jobs.
                process.kill()
                process.communicate()
                raise
    finally:
        if progress_path:
            Path(progress_path).unlink(missing_ok=True)
        if slot:
            slot.close()


def update_progress(job_id, path, duration):
    try:
        # Bounded tail: the progress file grows, but Python memory does not.
        with open(path, "rb") as handle:
            handle.seek(max(0, os.fstat(handle.fileno()).st_size - 8192))
            lines = handle.read().decode("utf-8", errors="ignore").splitlines()
        values = [int(line.split("=", 1)[1]) for line in lines if line.startswith("out_time_us=") and line.split("=", 1)[1].isdigit()]
        if values:
            progress = max(5, min(99, int(values[-1] / 1_000_000 / duration * 100)))
            from app.services.sync_db import sync_db
            sync_db.render_jobs.update_one(
                {"job_id": job_id, "status": "PROCESSING"},
                {"$max": {"progress": progress}},
            )
            return progress
    except Exception:
        logging.getLogger(__name__).warning("Could not update render progress for %s", job_id)
