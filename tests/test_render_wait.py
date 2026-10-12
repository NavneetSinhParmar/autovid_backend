import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.routes import render_jobs
from app.services import render_queue
from app.worker import video_worker
from app.utils.auth import get_optional_current_user


class RenderWaitTests(unittest.TestCase):
    def test_local_startup_restores_queued_jobs_and_skips_locked_jobs(self):
        db = Mock()
        db.render_jobs.find.return_value.sort.return_value = [{"job_id": "pending"}, {"job_id": "active"}]
        lock = Mock()
        lock.acquire.side_effect = [True, False]
        with patch.object(render_queue, "RENDER_QUEUE_BACKEND", "memory"), patch("app.services.sync_db.sync_db", db), patch.object(render_queue, "FileLock", return_value=lock), patch.object(video_worker, "_job_route", return_value=("image.task", "render_image")), patch.object(render_queue, "dispatch_render_task") as dispatch:
            self.assertEqual(render_queue.resume_local_pending_jobs(), 1)
        dispatch.assert_called_once_with("image.task", "pending", "render_image")
        db.render_jobs.find.assert_called_once_with({"status": "QUEUED"})

    def setUp(self):
        self.api = FastAPI()
        self.api.include_router(render_jobs.router)
        self.api.dependency_overrides[get_optional_current_user] = lambda: None
        self.queued = {"job_id": "example", "company_id": "tenant", "status": "QUEUED"}

    def test_long_poll_returns_completed_without_another_http_call(self):
        db = Mock()
        db.render_jobs.find_one = AsyncMock(return_value={**self.queued, "_id": "record", "status": "COMPLETED", "progress": 100})
        with patch.object(render_jobs, "_owned_job", AsyncMock(return_value=self.queued.copy())), patch.object(render_jobs, "db", db), TestClient(self.api) as client:
            response = client.get("/render-jobs/example?wait_seconds=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "COMPLETED")
        self.assertEqual(db.render_jobs.find_one.await_count, 1)

    def test_default_status_request_does_not_wait(self):
        with patch.object(render_jobs, "_owned_job", AsyncMock(return_value=self.queued.copy())), patch.object(render_jobs, "db") as db, TestClient(self.api) as client:
            response = client.get("/render-jobs/example")
        self.assertEqual(response.json()["status"], "QUEUED")
        db.render_jobs.find_one.assert_not_called()

    def test_long_poll_returns_on_progress_change_before_completion(self):
        db = Mock()
        job = {**self.queued, "status": "PROCESSING", "progress": 20}
        db.render_jobs.find_one = AsyncMock(return_value={**job, "_id": "record", "progress": 40})
        with patch.object(render_jobs, "_owned_job", AsyncMock(return_value=job)), patch.object(render_jobs, "db", db), TestClient(self.api) as client:
            response = client.get("/render-jobs/example?wait_seconds=15&wait_for_progress=true")
        self.assertEqual(response.json()["progress"], 40)
        self.assertEqual(db.render_jobs.find_one.await_count, 1)

    def test_unauthorized_request_is_rejected_before_waiting(self):
        with patch.object(render_jobs, "_owned_job", AsyncMock(side_effect=HTTPException(401, "Unauthorized"))), patch.object(render_jobs, "db") as db, TestClient(self.api) as client:
            response = client.get("/render-jobs/example?wait_seconds=15")
        self.assertEqual(response.status_code, 401)
        db.render_jobs.find_one.assert_not_called()

    def test_local_capacity_retry_is_delayed_instead_of_recursive(self):
        from celery.exceptions import Retry
        from app.services.render_resources import CapacityUnavailable
        task = Mock()
        task.apply.side_effect = [Retry(exc=CapacityUnavailable("busy"), when=5), None]
        celery_app = Mock(tasks={"test.task": task})
        with patch("app.services.celery_app.celery_app", celery_app), patch.object(render_queue, "_retry_sleep") as sleep:
            render_queue._execute_local_task("test.task", "example")
        sleep.assert_called_once_with(1)
        self.assertEqual(task.apply.call_count, 2)
        self.assertTrue(task.apply.call_args.kwargs["throw"])

    def test_local_startup_failure_marks_queued_job_failed(self):
        task = Mock()
        task.apply.side_effect = ModuleNotFoundError("missing dependency")
        celery_app = Mock(tasks={"test.task": task})
        db = Mock()
        with patch("app.services.celery_app.celery_app", celery_app), patch("app.services.sync_db.sync_db", db):
            render_queue._execute_local_task("test.task", "example")
        self.assertEqual(db.render_jobs.update_one.call_args.args[1]["$set"]["status"], "FAILED")

    def test_local_capacity_wait_has_a_deadline(self):
        from celery.exceptions import Retry
        from app.services.render_resources import CapacityUnavailable
        task = Mock()
        task.apply.side_effect = Retry(exc=CapacityUnavailable("Waiting for RAM"), when=5)
        db = Mock()
        with patch("app.services.celery_app.celery_app", Mock(tasks={"test.task": task})), patch("app.services.sync_db.sync_db", db), patch.object(render_queue, "_retry_clock", side_effect=[0, 100000]), patch.object(render_queue, "_retry_sleep") as sleep:
            render_queue._execute_local_task("test.task", "example")
        sleep.assert_not_called()
        self.assertEqual(db.render_jobs.update_one.call_args.args[1]["$set"]["error_code"], "RENDER_CAPACITY_TIMEOUT")
