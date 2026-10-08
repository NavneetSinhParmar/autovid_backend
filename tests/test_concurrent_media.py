import asyncio
import threading
import time
import tempfile
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock, patch

from app.services import render_queue, media_upload
from app.services.media_validator import ValidatedMedia
from app.services.storage import LocalStorageService


class ConcurrentMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_uses_speech_queue_only_when_voiceover_is_present(self):
        db = Mock()
        db.render_jobs.insert_one = AsyncMock()
        for voice in (False, True):
            with self.subTest(voice=voice), patch("app.db.connection.db", db), \
                 patch.object(render_queue, "ensure_media_folder"), \
                 patch.object(render_queue, "dispatch_render_task") as dispatch:
                payload = {"dynamic_tts": True, "template": {"template_json": {"design": {"trackItemsMap": {
                    "item": {"type": "audio" if voice else "image", "metadata": {
                        "isCustomerField": True, "fieldPath": "voiceover" if voice else "logo",
                    }, "voisetext": "Hello" if voice else ""},
                }}}}}
                await render_queue.enqueue_celery_render_job(
                    kind="video", extension="mp4", company_id="company", payload=payload,
                )
                self.assertEqual(dispatch.call_args.args[2], "tts" if voice else "render_video")
                self.assertTrue(payload["dynamic_tts"])

    async def test_100_identical_uploads_reuse_one_complete_file_per_company(self):
        storage = LocalStorageService()
        content = b"validated-media" * 1024
        with tempfile.TemporaryDirectory() as root, patch("app.services.storage.LOCAL_MEDIA_ROOT", root):
            paths = await asyncio.gather(*[
                asyncio.to_thread(storage.save_cached, content, "company", "upload.png")
                for _ in range(100)
            ])
            self.assertEqual(len(set(paths)), 1)
            self.assertEqual((Path(root) / paths[0]).read_bytes(), content)
            self.assertEqual(len(list((Path(root) / "company").iterdir())), 1)
            other = storage.save_cached(content, "other-company", "upload.png")
            self.assertNotEqual(paths[0], other)

    async def test_100_render_submissions_return_while_bounded_workers_are_busy(self):
        release = threading.Event()
        lock = threading.Lock()
        active = {"image": 0, "video": 0}
        peak = dict(active)
        completed = []
        pools = {"render_image": ThreadPoolExecutor(4), "render_video": ThreadPoolExecutor(2)}

        def render(task_name, job_id):
            kind = "image" if "image" in task_name else "video"
            with lock:
                active[kind] += 1
                peak[kind] = max(peak[kind], active[kind])
            release.wait(10)
            with lock:
                active[kind] -= 1
                completed.append(job_id)

        db = Mock()
        db.render_jobs.insert_one = AsyncMock()
        try:
            with patch.object(render_queue, "RENDER_QUEUE_BACKEND", "memory"), \
                 patch.object(render_queue, "_local_executors", pools), \
                 patch.object(render_queue, "_execute_local_task", side_effect=render), \
                 patch.object(render_queue, "ensure_media_folder"), \
                 patch("app.db.connection.db", db):
                jobs = await asyncio.wait_for(asyncio.gather(*[
                    render_queue.enqueue_celery_render_job(
                        kind="image" if i % 2 else "video", extension="jpg" if i % 2 else "mp4",
                        company_id="company", payload={},
                    ) for i in range(100)
                ]), 5)
                self.assertEqual(len({job["job_id"] for job in jobs}), 100)
                self.assertTrue(all(job["status"] == "QUEUED" for job in jobs))
                self.assertEqual(db.render_jobs.insert_one.await_count, 100)
                self.assertEqual(completed, [])
                self.assertEqual(peak, {"image": 4, "video": 2})
                release.set()
                for pool in pools.values():
                    await asyncio.to_thread(pool.shutdown, wait=True)
                self.assertEqual(len(completed), 100)
        finally:
            release.set()
            for pool in pools.values():
                pool.shutdown(wait=True)

    async def test_100_uploads_are_bounded_through_validation_and_storage(self):
        lock = threading.Lock()
        active = 0
        peak = 0

        async def validate(file):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.001)
            return ValidatedMedia(b"image", "image", "png", 5)

        def save(content, folder, name):
            nonlocal active
            time.sleep(0.005)
            with lock:
                active -= 1
            return f"{folder}/{name}"

        with patch.object(media_upload, "_upload_slots", asyncio.Semaphore(4)), \
             patch.object(media_upload.media_validator, "validate_media", side_effect=validate), \
             patch.object(media_upload.storage_service, "save_cached", side_effect=save):
            results = await asyncio.gather(*[
                media_upload.validate_and_store_media(Mock(filename=f"{i}.png"), "company")
                for i in range(100)
            ])
        self.assertEqual(len(results), 100)
        self.assertEqual(peak, 4)
        self.assertEqual(active, 0)
        self.assertTrue(all(media.content == b"" and media.size == 5 for media, path in results))
