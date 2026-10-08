import unittest
from app.services.public_media import references_media


class PublicMediaReferenceTests(unittest.TestCase):
    def test_saved_preview_and_editor_asset_paths_match(self):
        path = "company/asset.jpg"
        for source in ("./media/company/asset.jpg", "/media/company/asset.jpg",
                       "company/asset.jpg", "https://api.example/media/company/asset.jpg",
                       "/api/backend/media/company/asset.jpg"):
            with self.subTest(source=source):
                self.assertTrue(references_media({"design": {"item": {"details": {"src": source}}}}, path))

    def test_unrelated_company_assets_are_not_published(self):
        template = {"base_image_url": ["./media/company/public.jpg"]}
        self.assertFalse(references_media(template, "company/private.jpg"))
        self.assertFalse(references_media(template, "other/public.jpg"))
