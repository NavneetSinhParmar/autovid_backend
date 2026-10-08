import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from app.db.indexes import allow_local_legacy_indexes, ensure_user_unique_index
from app.routes.auth import LoginRequest, common_login


class LocalStartupTests(unittest.IsolatedAsyncioTestCase):
    def test_exception_requires_explicit_local_development(self):
        with patch.dict(os.environ, {"APP_ENV": "development", "ALLOW_LOCAL_LEGACY_USER_INDEXES": "true", "MONGO_URL": "mongodb://localhost:27017"}):
            self.assertTrue(allow_local_legacy_indexes())
            with patch.dict(os.environ, {"APP_ENV": "production"}):
                self.assertFalse(allow_local_legacy_indexes())
            with patch.dict(os.environ, {"MONGO_URL": "mongodb+srv://example.com"}):
                self.assertFalse(allow_local_legacy_indexes())

    async def test_production_duplicate_still_blocks_startup(self):
        with patch("app.db.indexes.db") as db, patch.dict(os.environ, {"APP_ENV": "production"}):
            db.users.create_index = AsyncMock(side_effect=DuplicateKeyError("duplicate"))
            with self.assertRaises(RuntimeError):
                await ensure_user_unique_index("email")

    async def test_ambiguous_login_never_checks_password(self):
        with patch("app.routes.auth.db") as db, patch("app.routes.auth.verify_password") as verify:
            cursor = Mock()
            cursor.limit.return_value.to_list = AsyncMock(return_value=[{}, {}])
            db.users.find.return_value = cursor
            with self.assertRaises(HTTPException) as error:
                await common_login(LoginRequest(username="duplicate", password="password"))
            self.assertEqual(error.exception.status_code, 409)
            verify.assert_not_called()
