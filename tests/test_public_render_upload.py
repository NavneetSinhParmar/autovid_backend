import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes.public_templates import router
from app.services.media_validator import ValidatedMedia


class PublicRenderUploadTests(unittest.TestCase):
    def test_public_upload_validates_template_without_mutating_it(self):
        api = FastAPI()
        api.include_router(router)
        collection = Mock()
        collection.find_one = AsyncMock(return_value={"company_id": "company"})
        media = ValidatedMedia(b"image", "image", "png", 5)
        with patch("app.routes.public_templates.db") as db, \
             patch("app.services.media_validator.validate_media", new=AsyncMock(return_value=media)), \
             patch("app.services.storage.storage_service.save_cached", return_value="company/personalization/image.png") as save, \
             patch("app.core.rate_limit._distributed_check", new=AsyncMock()):
            db.templates = collection
            with TestClient(api) as client:
                response = client.post(
                    "/public/templates/6abd509c624d8fc6deea5955/media",
                    files={"file": ("image.png", b"image", "image/png")},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["media"]["file_url"], "./media/company/personalization/image.png")
            query = collection.find_one.call_args.args[0]
            self.assertTrue(query["public"])
            self.assertEqual(query["status"], "active")
            collection.update_one.assert_not_called()
            save.assert_called_once()

    def test_unavailable_template_cannot_receive_anonymous_uploads(self):
        api = FastAPI()
        api.include_router(router)
        with patch("app.routes.public_templates.db") as db, \
             patch("app.services.storage.storage_service.save_cached") as save, \
             patch("app.core.rate_limit._distributed_check", new=AsyncMock()):
            db.templates.find_one = AsyncMock(return_value=None)
            with TestClient(api) as client:
                response = client.post(
                    "/public/templates/6abd509c624d8fc6deea5955/media",
                    files={"file": ("image.png", b"image", "image/png")},
                )
            self.assertEqual(response.status_code, 404)
            save.assert_not_called()
