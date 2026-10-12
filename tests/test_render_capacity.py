import asyncio
import io
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import UploadFile
from app.core.errors import AppError
from app.services import render_resources as resources, render_queue, media_validator
from app.services.ffmpeg_process import run_ffmpeg, update_progress
from app.services.storage import LocalStorageService
from app.services.svg_raster import svg_to_png


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RENDER_LOCK_DIR": self.folder.name})
        self.env.start()
        self.config = patch.object(resources, "settings", replace(resources.settings, max_concurrent_video_renders=2, min_free_memory_mb=100, estimated_render_memory_mb=50))
        self.config.start()
        self.memory = patch.object(resources, "available_memory_mb", return_value=10000)
        self.memory.start()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.env.stop)
        self.addCleanup(self.config.stop)
        self.addCleanup(self.memory.stop)

    def test_process_slots_are_global_and_release_after_close(self):
        first, second = resources.acquire_render_slot(), resources.acquire_render_slot()
        try:
            with self.assertRaises(resources.CapacityUnavailable):
                resources.acquire_render_slot()
        finally:
            first.close()
            second.close()
        slot = resources.acquire_render_slot()
        slot.close()

    def test_lock_is_visible_in_another_python_process(self):
        lock = resources.FileLock("shared")
        self.assertTrue(lock.acquire())
        try:
            result = subprocess.run([sys.executable, "-c", "from app.services.render_resources import FileLock; import sys; lock=FileLock('shared'); sys.exit(1 if lock.acquire() else 0)"], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            lock.close()

    def test_low_memory_does_not_launch_or_leak_slots(self):
        with patch.object(resources, "available_memory_mb", return_value=20), patch("app.services.ffmpeg_process.subprocess.Popen") as launch:
            with self.assertRaises(resources.CapacityUnavailable):
                run_ffmpeg([sys.executable, "-c", "pass"])
            launch.assert_not_called()
        slot = resources.acquire_render_slot()
        slot.close()

    def test_failed_subprocess_and_timeout_release_capacity(self):
        with self.assertRaises(subprocess.CalledProcessError):
            run_ffmpeg([sys.executable, "-c", "raise SystemExit(7)"], check=True)
        with self.assertRaises(subprocess.TimeoutExpired):
            run_ffmpeg([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.1)
        slot = resources.acquire_render_slot()
        slot.close()

    def test_duplicate_execution_never_enters_render_body(self):
        lock = resources.FileLock("job_duplicate")
        lock.acquire()
        calls = []
        @resources.isolated_job()
        def work(task, job_id):
            calls.append(job_id)
        try:
            task = Mock()
            task.retry.side_effect = RuntimeError("retry")
            with self.assertRaisesRegex(RuntimeError, "retry"):
                work(task, "duplicate")
            self.assertEqual(calls, [])
        finally:
            lock.close()
        work(Mock(), "duplicate")
        self.assertEqual(calls, ["duplicate"])

    def test_capacity_retry_happens_before_job_claim(self):
        task, body = Mock(), Mock()
        task.retry.side_effect = RuntimeError("retry")
        @resources.isolated_job(reserve_ffmpeg=True)
        def work(task, job_id):
            body()
        with patch.object(resources, "available_memory_mb", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "retry"):
                work(task, "waiting")
        body.assert_not_called()
        self.assertIsNone(task.retry.call_args.kwargs["max_retries"])

    def test_progress_is_time_based_and_never_marks_completed(self):
        progress = Path(self.folder.name) / "progress.txt"
        progress.write_text("out_time_us=5000000\nprogress=continue\n")
        db = Mock()
        with patch("app.services.sync_db.sync_db", db):
            update_progress("example", str(progress), 10)
        update = db.render_jobs.update_one.call_args.args
        self.assertEqual(update[1], {"$max": {"progress": 50}})
        self.assertEqual(update[0]["status"], "PROCESSING")

    @unittest.skipUnless(os.name == "posix", "Linux descriptor inheritance required")
    def test_child_keeps_slot_when_parent_is_killed(self):
        script = "from app.services.render_resources import FileLock; import subprocess,sys,time; lock=FileLock('orphan'); assert lock.acquire(); p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'],pass_fds=(lock.fd,)); print(p.pid,flush=True); time.sleep(10)"
        parent = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        child_pid = int(parent.stdout.readline())
        try:
            parent.kill()
            parent.wait()
            other = resources.FileLock("orphan")
            self.assertFalse(other.acquire())
        finally:
            import signal
            os.kill(child_pid, signal.SIGTERM)
            if parent.poll() is None:
                parent.kill()
                parent.wait()


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_overflow_returns_429_before_insert(self):
        db = Mock()
        db.render_jobs.count_documents = AsyncMock(return_value=10000)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"RENDER_LOCK_DIR": root}), patch("app.db.connection.db", db):
            with self.assertRaises(AppError) as raised:
                await render_queue.enqueue_celery_render_job(kind="video", extension="mp4", company_id="tenant")
        self.assertEqual(raised.exception.status_code, 429)
        db.render_jobs.insert_one.assert_not_called()

    async def test_two_submissions_cannot_take_the_last_slot(self):
        records = []
        db = Mock()
        db.render_jobs.count_documents = AsyncMock(side_effect=lambda query: len(records))
        db.render_jobs.insert_one = AsyncMock(side_effect=lambda record: records.append(record))
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"RENDER_LOCK_DIR": root}), patch("app.db.connection.db", db), patch.object(render_queue, "settings", replace(render_queue.settings, max_pending_render_jobs=1)), patch.object(render_queue, "ensure_media_folder"), patch.object(render_queue, "dispatch_render_task"):
            results = await asyncio.gather(*[render_queue.enqueue_celery_render_job(kind="video", extension="mp4", company_id="tenant") for _ in range(2)], return_exceptions=True)
        self.assertEqual(len(records), 1)
        self.assertEqual(sum(isinstance(result, AppError) for result in results), 1)

    async def test_publish_failure_keeps_durable_queued_job(self):
        db = Mock()
        db.render_jobs.count_documents = AsyncMock(return_value=0)
        db.render_jobs.insert_one = AsyncMock()
        db.render_jobs.update_one = AsyncMock()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"RENDER_LOCK_DIR": root}), patch("app.db.connection.db", db), patch.object(render_queue, "ensure_media_folder"), patch.object(render_queue, "dispatch_render_task", side_effect=ConnectionError("offline")):
            with self.assertRaises(AppError):
                await render_queue.enqueue_celery_render_job(kind="video", extension="mp4", company_id="tenant")
        self.assertEqual(db.render_jobs.update_one.call_args.args[1]["$set"]["status"], "QUEUED")


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_jpeg_and_png_validate(self):
        from PIL import Image
        for extension, mime, format_name in [("jpeg", "image/jpeg", "JPEG"), ("png", "image/png", "PNG")]:
            data = io.BytesIO()
            Image.new("RGB", (12, 8), "red").save(data, format_name)
            result = await media_validator.validate_image(UploadFile(filename="logo." + extension, file=io.BytesIO(data.getvalue()), headers={"content-type": mime}))
            self.assertEqual((result.width, result.height), (12, 8))

    def test_svg_blocks_remote_file_entity_and_css_references(self):
        cases = [b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="file:///etc/passwd"/></svg>',
                 b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="https://example.com/a"/></svg>',
                 b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><style>@import "https://example.com";</style></svg>',
                 b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">&x;</svg>']
        for content in cases:
            with self.assertRaises(AppError) as raised:
                svg_to_png(content)
            self.assertEqual(raised.exception.status_code, 400)

    async def test_svg_is_stored_as_png_in_legacy_logo_routes(self):
        try:
            import cairosvg
        except (ImportError, OSError):
            self.skipTest("Native Cairo required; run Linux deployment suite")
        upload = UploadFile(filename="logo.svg", file=io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16" fill="red"/></svg>'), headers={"content-type": "image/svg+xml"})
        result = await media_validator.validate_image(upload)
        self.assertEqual(result.extension, "png")
        self.assertEqual(upload.filename, "logo.png")
        await upload.seek(0)
        self.assertTrue((await upload.read()).startswith(b"\x89PNG"))

    async def test_video_streaming_and_cleanup(self):
        upload = UploadFile(filename="video.mp4", file=io.BytesIO(b"content" * 1000), headers={"content-type": "video/mp4"})
        probe = {"format": {"duration": "5"}, "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720}]}
        with patch.object(media_validator, "_probe", return_value=probe):
            result = await media_validator.validate_video(upload, stream_to_disk=True)
        try:
            self.assertEqual(result.content, b"")
            self.assertEqual(Path(result.temporary_path).read_bytes(), b"content" * 1000)
            with tempfile.TemporaryDirectory() as root, patch("app.services.storage.LOCAL_MEDIA_ROOT", root):
                storage = LocalStorageService()
                first = storage.save_cached_file(result.temporary_path, "tenant", "video.mp4")
                second = storage.save_cached_file(result.temporary_path, "tenant", "video.mp4")
                self.assertEqual(first, second)
                self.assertEqual(len(list((Path(root) / "tenant").iterdir())), 1)
        finally:
            Path(result.temporary_path).unlink()

    async def test_video_duration_limit_is_enforced(self):
        upload = UploadFile(filename="video.mp4", file=io.BytesIO(b"video"), headers={"content-type": "video/mp4"})
        probe = {"format": {"duration": "99999"}, "streams": [{"codec_type": "video"}]}
        with patch.object(media_validator, "_probe", return_value=probe):
            with self.assertRaises(AppError) as raised:
                await media_validator.validate_video(upload)
        self.assertEqual(raised.exception.detail["code"], "VIDEO_TOO_LONG")

    def test_remote_asset_is_streamed_once_and_reused_within_job(self):
        from app.services import video_renderer as renderer
        from app.services.render_queue import current_render_temp_dir
        response = Mock()
        response.iter_content.return_value = [b"media", b"bytes"]
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as root, patch.object(renderer.requests, "get", return_value=context) as download, patch.dict(os.environ, {"REMOTE_ASSET_CACHE": "true"}):
            token = current_render_temp_dir.set(root)
            try:
                first = renderer.normalize_media_src("https://example.com/asset.mp4")
                second = renderer.normalize_media_src("https://example.com/asset.mp4")
                self.assertEqual(first, second)
                self.assertEqual(Path(first).read_bytes(), b"mediabytes")
                download.assert_called_once()
                self.assertTrue(download.call_args.kwargs["stream"])
            finally:
                current_render_temp_dir.reset(token)
