import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from app.worker import video_worker as worker
from app.services.render_resources import FileLock


class Cursor(list):
    def limit(self, count):
        return Cursor(self[:count])


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.env = patch.dict(os.environ, {"RENDER_LOCK_DIR": self.root.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = Mock()
        self.db.render_jobs.update_one.return_value = Mock(modified_count=1)
        self.db.campaigns.find.return_value = Cursor()
        self.job = {"_id": "record", "job_id": "crashed", "status": "PROCESSING", "retry_count": 0,
                    "updated_at": datetime.utcnow() - timedelta(hours=1), "output_relative_path": "render_jobs/crashed/output/output.mp4"}

    def test_crash_recovery_requeues_free_job_once(self):
        self.db.render_jobs.find.side_effect = [Cursor([self.job]), Cursor()]
        with patch.object(worker, "sync_db", self.db), patch.object(worker, "dispatch_render_task") as dispatch:
            result = worker.recover_stuck_jobs.run()
        self.assertEqual(result["requeued"], 1)
        dispatch.assert_called_once_with("app.worker.video_worker.render_video_task", "crashed", "render_video")

    def test_recovery_does_not_touch_live_or_orphaned_execution(self):
        lock = FileLock("job_crashed")
        lock.acquire()
        self.db.render_jobs.find.side_effect = [Cursor([self.job]), Cursor()]
        try:
            with patch.object(worker, "sync_db", self.db), patch.object(worker, "dispatch_render_task") as dispatch:
                result = worker.recover_stuck_jobs.run()
            self.assertEqual(result["requeued"], 0)
            dispatch.assert_not_called()
            self.db.render_jobs.update_one.assert_not_called()
        finally:
            lock.close()

    def test_recovery_respects_retry_budget_and_compare_and_swap(self):
        job = {**self.job, "retry_count": 100}
        cutoff = datetime.utcnow()
        with patch.object(worker, "sync_db", self.db):
            result = worker._recover_processing_job(job, cutoff)
        self.assertEqual(result, "FAILED")
        self.assertEqual(self.db.render_jobs.update_one.call_args.args[0]["updated_at"], {"$lt": cutoff})
        self.db.render_jobs.update_one.return_value.modified_count = 0
        with patch.object(worker, "sync_db", self.db):
            self.assertIsNone(worker._recover_processing_job(job, cutoff))

    def test_interrupted_publication_republishes_queued_job(self):
        job = {**self.job, "status": "QUEUED"}
        self.db.render_jobs.find.side_effect = [Cursor(), Cursor([job])]
        with patch.object(worker, "sync_db", self.db), patch.object(worker, "dispatch_render_task") as dispatch:
            result = worker.recover_stuck_jobs.run()
        self.assertEqual(result["requeued"], 1)
        dispatch.assert_called_once()

    def test_worker_failure_retries_and_cleans_only_temp(self):
        from celery.exceptions import Retry
        job = {**self.job, "folder": "render_jobs/crashed", "tmp_folder": "render_jobs/crashed/temp",
               "started_at": datetime.utcnow(), "payload": {}, "output_relative_path": "render_jobs/crashed/output/output.mp4"}
        self.db.render_jobs.find_one_and_update.return_value = job
        task = Mock()
        task.request.id = "task-id"
        task.request.hostname = "test"
        task.retry.side_effect = Retry()
        body = worker.render_video_task.run.__wrapped__
        with patch.object(worker, "sync_db", self.db), patch.object(worker, "ensure_media_folder"), \
             patch.object(worker, "get_media_abs_path", side_effect=lambda path: str(Path(self.root.name) / path)), \
             patch.object(worker, "_start_job_heartbeat", return_value=Mock()), patch.object(worker, "_safe_cleanup_tmp") as cleanup:
            with self.assertRaises(Retry):
                body(task, "crashed")
        updates = [call.args[1]["$set"] for call in self.db.render_jobs.update_one.call_args_list]
        self.assertTrue(any(value.get("status") == "QUEUED" and value.get("retry_count") == 1 for value in updates))
        cleanup.assert_called_once_with("render_jobs/crashed/temp")

    def test_cleanup_preserves_completed_output(self):
        with patch("app.services.storage.LOCAL_MEDIA_ROOT", self.root.name), patch.dict(os.environ, {"LOCAL_MEDIA_ROOT": self.root.name}):
            temp = Path(self.root.name) / "render_jobs" / "job" / "temp"
            output = temp.parent / "output"
            temp.mkdir(parents=True)
            output.mkdir()
            (temp / "input.txt").write_text("temporary")
            (output / "output.mp4").write_bytes(b"completed")
            worker._safe_cleanup_tmp("render_jobs/job/temp")
            self.assertFalse(temp.exists())
            self.assertTrue((output / "output.mp4").exists())
            with self.assertRaises(ValueError):
                worker._safe_cleanup_tmp("render_jobs/job/output")
