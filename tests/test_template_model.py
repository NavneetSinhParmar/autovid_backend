import unittest

from app.models.template_model import TemplateCreate, TemplateUpdate


class TemplateMediaValidationTests(unittest.TestCase):
    def test_long_video_duration_can_be_created_and_updated(self):
        template = TemplateCreate(template_name="Long video", duration=900)
        update = TemplateUpdate(duration=900)
        self.assertEqual(template.duration, 900)
        self.assertEqual(update.duration, 900)

    def test_empty_media_arrays_become_none(self):
        template = TemplateCreate(
            template_name="Example",
            base_video_url=[],
            base_audio_url=[],
        )

        self.assertIsNone(template.base_video_url)
        self.assertIsNone(template.base_audio_url)

    def test_latest_uploaded_image_becomes_primary_url(self):
        template = TemplateCreate(
            template_name="Example",
            base_image_url=[
                "./media/company/first.jpg",
                "./media/company/second.jpg",
            ],
        )

        self.assertEqual(template.base_image_url, "./media/company/second.jpg")

    def test_update_accepts_existing_string_contract(self):
        update = TemplateUpdate(base_video_url="./media/company/video.mp4")

        self.assertEqual(update.base_video_url, "./media/company/video.mp4")

    def test_template_json_keeps_complete_editor_media_data(self):
        media_urls = ["./media/company/first.jpg", "./media/company/second.jpg"]
        template = TemplateCreate(
            template_name="Example",
            base_image_url=media_urls,
            template_json={"assets": {"images": media_urls}},
        )

        self.assertEqual(template.template_json["assets"]["images"], media_urls)


if __name__ == "__main__":
    unittest.main()
