import unittest
from unittest.mock import patch


class MediaUrlTests(unittest.TestCase):
    def test_build_media_url_accepts_stored_media_prefix(self):
        with patch("app.services.url.BASE_URL", "http://api.test"):
            from app.services.url import build_media_url

            self.assertEqual(
                build_media_url("./media/company/templates/template/image.jpg"),
                "http://api.test/media/company/templates/template/image.jpg",
            )

    def test_build_media_url_accepts_relative_storage_path(self):
        with patch("app.services.url.BASE_URL", "http://api.test/"):
            from app.services.url import build_media_url

            self.assertEqual(
                build_media_url("company/templates/template/image.jpg"),
                "http://api.test/media/company/templates/template/image.jpg",
            )

    def test_build_media_url_leaves_absolute_urls_unchanged(self):
        from app.services.url import build_media_url

        self.assertEqual(
            build_media_url("https://cdn.test/image.jpg"),
            "https://cdn.test/image.jpg",
        )


if __name__ == "__main__":
    unittest.main()
