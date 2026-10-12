import io
import os
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DATABASE_NAME", "autovid_test")
os.environ.setdefault("SECRET_KEY", "unit-test-secret-that-is-longer-than-32-bytes")

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.datastructures import FormData

from app.core.tenancy import company_object_id_filter, object_id
from app.routes.auth import PublicRegistrationRequest, register_user
from app.routes.customer import (
    _build_logo_maps,
    _logo_files_from_form,
    _normalize_logo_filename,
    _resolve_logo_file,
)
from app.services.media_validator import validate_image, validate_media, validate_video
from app.services.output_validator import validate_generated_video
from app.services.storage import get_media_abs_path


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    def test_registration_requires_strong_password(self):
        with self.assertRaises(ValidationError):
            PublicRegistrationRequest(username="user", email="user@example.com", password="short")

    async def test_public_registration_rejects_privileged_role_before_database_access(self):
        request = PublicRegistrationRequest(
            username="attacker", email="attacker@example.com",
            password="a-secure-password", role="superadmin",
        )
        with self.assertRaises(HTTPException) as raised:
            await register_user(request)
        self.assertEqual(raised.exception.status_code, 403)

    def test_invalid_object_id_is_a_client_error(self):
        with self.assertRaises(HTTPException) as raised:
            object_id("not-an-object-id")
        self.assertEqual(raised.exception.status_code, 400)

    def test_company_filter_supports_migration_window(self):
        result = company_object_id_filter("507f1f77bcf86cd799439011")
        self.assertEqual(len(result["$in"]), 2)


class UploadValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_jpg_alias_mime_is_accepted(self):
        from PIL import Image

        content = io.BytesIO()
        Image.new("RGB", (1, 1)).save(content, format="JPEG")
        upload = UploadFile(
            filename="customer_logo1.jpg",
            file=io.BytesIO(content.getvalue()),
            headers={"content-type": "image/jpg"},
        )

        validated = await validate_image(upload)

        self.assertEqual(validated.extension, "jpg")

    async def test_unsupported_extension_has_stable_error_code(self):
        upload = UploadFile(filename="payload.exe", file=io.BytesIO(b"not-media"))
        with self.assertRaises(HTTPException) as raised:
            await validate_media(upload)
        self.assertEqual(raised.exception.detail["code"], "UNSUPPORTED_FORMAT")

    async def test_mime_mismatch_has_stable_error_code(self):
        upload = UploadFile(
            filename="image.jpg", file=io.BytesIO(b"not-an-image"),
            headers={"content-type": "application/x-msdownload"},
        )
        with self.assertRaises(HTTPException) as raised:
            await validate_media(upload)
        self.assertEqual(raised.exception.detail["code"], "INVALID_MEDIA_TYPE")

    def test_storage_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            get_media_abs_path("../secrets.txt")

    async def test_source_video_over_five_minutes_is_accepted(self):
        upload = UploadFile(
            filename="source.mp4", file=io.BytesIO(b"video-bytes"),
            headers={"content-type": "video/mp4"},
        )
        probe = {
            "format": {"duration": "300.5"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720}],
        }
        from app.services.media_validator import settings as validator_settings
        with patch("app.services.media_validator._probe", return_value=probe), patch("app.services.media_validator.settings", replace(validator_settings, max_source_video_seconds=1800)):
            media = await validate_video(upload)
        self.assertEqual(media.duration, 300.5)

    def test_generated_video_over_one_minute_is_accepted(self):
        result = Mock(returncode=0, stdout='{"format":{"duration":"61"},"streams":[{"codec_type":"video","codec_name":"h264","width":1280,"height":720}]}')
        from app.services.output_validator import settings as output_settings
        with patch("app.services.output_validator.subprocess.run", return_value=result), patch("app.services.output_validator.settings", replace(output_settings, max_output_video_seconds=900)):
            metadata = validate_generated_video("output.mp4")
        self.assertEqual(metadata["duration"], 61)


class BulkCustomerLogoTests(unittest.TestCase):
    def test_blank_excel_logo_cell_is_ignored(self):
        self.assertEqual(_normalize_logo_filename(None), "")

    def test_extensionless_logo_name_matches_uploaded_image(self):
        upload = UploadFile(
            filename="customer_logo1.PNG",
            file=io.BytesIO(b"image-bytes"),
            headers={"content-type": "image/png"},
        )
        by_filename, by_stem = _build_logo_maps([upload])

        resolved = _resolve_logo_file("customer_logo1", by_filename, by_stem, 2)

        self.assertIs(resolved, upload)

    def test_logo_path_is_matched_by_basename(self):
        upload = UploadFile(
            filename="customer_logo1.jpg",
            file=io.BytesIO(b"image-bytes"),
            headers={"content-type": "image/jpeg"},
        )
        by_filename, by_stem = _build_logo_maps([upload])
        reference = _normalize_logo_filename(r"C:\fakepath\customer_logo1.jpg")

        resolved = _resolve_logo_file(reference, by_filename, by_stem, 2)

        self.assertIs(resolved, upload)

    def test_csv_extension_can_match_uploaded_file_with_same_stem(self):
        upload = UploadFile(
            filename="customer_logo29.jpeg",
            file=io.BytesIO(b"image-bytes"),
            headers={"content-type": "image/jpeg"},
        )
        by_filename, by_stem = _build_logo_maps([upload])

        resolved = _resolve_logo_file("customer_logo29.png", by_filename, by_stem, 30)

        self.assertIs(resolved, upload)

    def test_bracketed_multipart_logo_field_is_accepted(self):
        first = UploadFile(filename="customer_logo1.jpeg", file=io.BytesIO(b"first"))
        second = UploadFile(filename="customer_logo3.jpeg", file=io.BytesIO(b"second"))
        form = FormData([("logo_files[]", first), ("logo_files[]", second)])

        resolved = _logo_files_from_form(form, [])

        self.assertEqual(resolved, [first, second])

    def test_bracketed_files_survive_real_multipart_parsing(self):
        app = FastAPI()

        @app.post("/bulk-test")
        async def bulk_test(
            request: Request,
            excel_file: UploadFile = File(...),
            logo_files: list[UploadFile] = File(default=[]),
        ):
            await excel_file.read()
            resolved = _logo_files_from_form(await request.form(), logo_files)
            return {"filenames": [upload.filename for upload in resolved]}

        response = TestClient(app).post(
            "/bulk-test",
            files=[
                ("excel_file", ("customers.csv", b"full_name,password\nTest,secret", "text/csv")),
                ("logo_files[]", ("customer_logo1.jpeg", b"first", "image/jpeg")),
                ("logo_files[]", ("customer_logo3.jpeg", b"second", "image/jpeg")),
            ],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["filenames"],
            ["customer_logo1.jpeg", "customer_logo3.jpeg"],
        )

    def test_extensionless_logo_automatically_prefers_png(self):
        png = UploadFile(filename="logo.png", file=io.BytesIO(b"png"))
        jpg = UploadFile(filename="logo.jpg", file=io.BytesIO(b"jpg"))
        by_filename, by_stem = _build_logo_maps([png, jpg])

        resolved = _resolve_logo_file("logo", by_filename, by_stem, 7)

        self.assertIs(resolved, png)

    def test_missing_csv_extension_falls_back_to_uploaded_format(self):
        jpeg = UploadFile(filename="logo.jpeg", file=io.BytesIO(b"jpeg"))
        by_filename, by_stem = _build_logo_maps([jpeg])

        resolved = _resolve_logo_file("logo.png", by_filename, by_stem, 7)

        self.assertIs(resolved, jpeg)


if __name__ == "__main__":
    unittest.main()
