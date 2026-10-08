"""Run: python test_company_api.py. Uses a disposable Mongo database and API server."""
import io
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

import requests
from bson import ObjectId
from pymongo import MongoClient

import app  # Load project .env.local before reading configuration.


ROOT = Path(__file__).resolve().parent


class CompanyAPI(unittest.TestCase):
    base_url = ""
    database = None

    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        response = requests.post(cls.base_url + "/auth/login", json={
            "username": "api_test_admin", "password": os.environ["API_TEST_ADMIN_PASSWORD"],
        }, timeout=20)
        if response.status_code != 200:
            raise RuntimeError(f"Test admin login failed: HTTP {response.status_code}")
        cls.admin = {"Authorization": "Bearer " + response.json()["access_token"]}
        cls.a = cls.create_company("A")
        cls.b = cls.create_company("B")
        cls.company = cls.login(cls.a["username"], cls.password)

    @classmethod
    def create_company(cls, label):
        username = "api_test_" + uuid.uuid4().hex
        response = requests.post(cls.base_url + "/company/", headers=cls.admin, data={
            "username": username, "email": username + "@example.com",
            "password": cls.password, "company_name": "API Test " + label,
            "mobile": "9999999999", "visibility": "private",
        }, timeout=20)
        if response.status_code != 200:
            raise AssertionError(f"Company create failed: HTTP {response.status_code}")
        return {**response.json(), "username": username}

    @classmethod
    def login(cls, username, password):
        response = requests.post(cls.base_url + "/auth/login", json={
            "username": username, "password": password,
        }, timeout=20)
        if response.status_code != 200:
            raise AssertionError(f"Login failed: HTTP {response.status_code}")
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def call(self, method, path, expected=200, headers=None, **kwargs):
        response = requests.request(method, self.base_url + path,
                                    headers=self.admin if headers is None else headers,
                                    timeout=20, **kwargs)
        self.assertEqual(response.status_code, expected, f"{method} {path}: expected {expected}, got {response.status_code}")
        return response.json()

    def test_health_and_openapi(self):
        self.assertEqual(self.call("GET", "/health")["status"], "ok")
        paths = self.call("GET", "/openapi.json")["paths"]
        self.assertIn("/company/", paths)
        self.assertIn("/company/{company_id}", paths)

    def test_company_password_is_hashed(self):
        row = self.database.users.find_one({"_id": ObjectId(self.a["user_id"])})
        self.assertNotEqual(row["password"], self.password)
        self.assertTrue(row["password"].startswith("$2"))

    def test_login_wrong_password(self):
        self.call("POST", "/auth/login", expected=401, headers={}, json={
            "username": self.a["username"], "password": "incorrect-password",
        })

    def test_company_profile_and_own_detail(self):
        self.assertEqual(self.call("GET", "/auth/profile", headers=self.company)["role"], "company")
        detail = self.call("GET", "/company/" + self.a["company_id"], headers=self.company)
        self.assertEqual(detail["company_id"], self.a["company_id"])
        self.assertNotIn("password", detail)

    def test_company_isolation_and_permissions(self):
        self.call("GET", "/company/" + self.b["company_id"], expected=404, headers=self.company)
        self.call("GET", "/company/", expected=403, headers=self.company)
        self.call("PATCH", "/company/" + self.b["company_id"], expected=403,
                  headers=self.company, data={"company_name": "unauthorized"})
        self.call("DELETE", "/company/" + self.b["company_id"], expected=403, headers=self.company)
        self.call("GET", "/company/", expected=401, headers={})

    def test_pagination_search_sort(self):
        first = self.call("GET", "/company/", params={"page": 1, "limit": 1,
            "search": "API Test", "sort_by": "company_name", "sort_order": "asc"})
        self.assertEqual(first["page"], 1)
        self.assertEqual(len(first["companies"]), 1)
        self.assertGreaterEqual(first["total"], 2)
        self.assertTrue(first["has_next"])
        self.assertNotIn("password", first["companies"][0])
        self.call("GET", "/company/", expected=422, params={"limit": 201})

    def test_update_and_filter(self):
        company = self.create_company("Update")
        path = "/company/" + company["company_id"]
        self.call("PATCH", path, data={"company_name": "Updated API Company", "visibility": "public"})
        self.assertEqual(self.call("GET", path)["company_name"], "Updated API Company")
        result = self.call("GET", "/company/", params={"visibility": "public", "search": "Updated API Company"})
        self.assertEqual(result["total"], 1)
        self.call("PATCH", path, expected=400, data={"visibility": "invalid"})
        self.call("PATCH", path, expected=400)

    def test_duplicate_company_rejected(self):
        self.call("POST", "/company/", expected=400, data={
            "username": self.a["username"], "email": "different@example.com",
            "password": self.password, "company_name": "Duplicate", "mobile": "123",
        })

    def test_invalid_and_missing_company(self):
        self.call("GET", "/company/invalid", expected=400)
        self.call("GET", "/company/" + str(ObjectId()), expected=404)

    def test_password_validation(self):
        self.call("POST", "/company/", expected=422, data={
            "username": "weak_password_test", "email": "weak@example.com",
            "password": "short", "company_name": "Weak", "mobile": "123",
        })
        self.call("PATCH", "/auth/reset-password", headers=self.company, expected=422,
                  json={"old_password": self.password, "new_password": "short"})
        self.call("PATCH", "/auth/forgot-password", expected=400,
                  json={"user_id": "invalid", "new_password": self.password})

    def test_company_resource_lists(self):
        for path, key in [("/customer/", "customers"), ("/category/", "categories"),
                          ("/templates/", "templates"), ("/media-api", "items"),
                          ("/campaigns", "items"), ("/render-jobs", "items")]:
            with self.subTest(path=path):
                result = self.call("GET", path, headers=self.company, params={"page": 1, "limit": 10})
                self.assertIsInstance(result[key], list)
                self.assertIn("has_next", result)
                self.assertEqual(result["total"], 0)

    def test_invalid_logo_does_not_leave_user(self):
        username = "bad_logo_" + uuid.uuid4().hex
        self.call("POST", "/company/", expected=400, data={
            "username": username, "email": username + "@example.com",
            "password": self.password, "company_name": "Bad logo", "mobile": "123",
        }, files={"logo_file": ("bad.exe", b"invalid", "application/octet-stream")})
        self.assertIsNone(self.database.users.find_one({"username": username}))

    def test_password_reset(self):
        company = self.create_company("Password")
        headers = self.login(company["username"], self.password)
        new_password = secrets.token_urlsafe(24)
        self.call("PATCH", "/auth/reset-password", headers=headers, expected=400,
                  json={"old_password": "wrong", "new_password": new_password})
        self.call("PATCH", "/auth/reset-password", headers=headers, expected=403,
                  json={"user_id": self.b["user_id"], "new_password": new_password})
        self.call("PATCH", "/auth/reset-password", headers=headers,
                  json={"old_password": self.password, "new_password": new_password})
        self.call("POST", "/auth/login", headers={}, expected=401,
                  json={"username": company["username"], "password": self.password})
        self.login(company["username"], new_password)
        self.call("PATCH", "/auth/forgot-password", json={
            "user_id": company["user_id"], "new_password": self.password,
        })
        self.login(company["username"], self.password)

    def test_logout_revokes_token(self):
        company = self.create_company("Logout")
        headers = self.login(company["username"], self.password)
        self.call("POST", "/auth/logout", headers=headers)
        self.call("GET", "/auth/profile", headers=headers, expected=401)

    def test_logo_upload_and_private_access(self):
        from PIL import Image
        content = io.BytesIO()
        Image.new("RGB", (16, 16), "red").save(content, format="PNG")
        company = self.create_company("Logo")
        path = "/company/" + company["company_id"]
        self.call("PATCH", path, files={"logo_file": ("logo.png", content.getvalue(), "image/png")})
        logo_url = self.call("GET", path)["logo_url"]
        response = requests.get(logo_url, headers=self.admin, timeout=20)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("image/"))
        self.assertEqual(requests.get(logo_url, headers=self.company, timeout=20).status_code, 404)
        self.call("PATCH", path, expected=400,
                  files={"logo_file": ("bad.exe", b"invalid", "application/octet-stream")})

    def test_delete_removes_company_and_login(self):
        company = self.create_company("Delete")
        self.call("DELETE", "/company/" + company["company_id"])
        self.call("GET", "/company/" + company["company_id"], expected=404)
        self.call("POST", "/auth/login", headers={}, expected=401,
                  json={"username": company["username"], "password": self.password})
        self.assertIsNone(self.database.users.find_one({"_id": ObjectId(company["user_id"])}))


def main():
    database_name = "autovid_api_test_" + uuid.uuid4().hex
    mongo = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"), serverSelectionTimeoutMS=5000)
    server = None
    try:
        mongo.admin.command("ping")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="autovid_api_test_") as directory:
            env = dict(os.environ)
            admin_password = secrets.token_urlsafe(32)
            env.update({"DATABASE_NAME": database_name, "SECRET_KEY": secrets.token_urlsafe(48),
                "APP_ENV": "test", "ALLOW_LOCAL_LEGACY_USER_INDEXES": "false",
                "LOCAL_MEDIA_ROOT": directory, "BOOTSTRAP_SUPERADMIN_USERNAME": "api_test_admin",
                "BOOTSTRAP_SUPERADMIN_EMAIL": "api_test_admin@example.com",
                "BOOTSTRAP_SUPERADMIN_PASSWORD": admin_password,
                "REDIS_URL": "redis://127.0.0.1:1/0"})
            os.environ["API_TEST_ADMIN_PASSWORD"] = admin_password
            CompanyAPI.base_url = f"http://127.0.0.1:{port}"
            CompanyAPI.database = mongo[database_name]
            with open(Path(directory) / "server.log", "w", encoding="utf-8") as log:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
                    "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
                    stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        if server.poll() is not None:
                            raise RuntimeError("Temporary API failed to start; check dependencies and Mongo permissions")
                        try:
                            if requests.get(CompanyAPI.base_url + "/health", timeout=1).status_code == 200:
                                break
                        except requests.RequestException:
                            pass
                        time.sleep(0.25)
                    else:
                        raise RuntimeError("Temporary API startup timed out")
                    print(f"Testing actual HTTP APIs with isolated database {database_name}", flush=True)
                    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CompanyAPI)
                    result = unittest.TextTestRunner(verbosity=2).run(suite)
                    return 0 if result.wasSuccessful() else 1
                finally:
                    if server.poll() is None:
                        server.terminate()
                        try:
                            server.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            server.kill()
                            server.wait()
    finally:
        # Only the generated database for this run is eligible for cleanup.
        if database_name.startswith("autovid_api_test_") and len(database_name) == 49:
            mongo.drop_database(database_name)
        mongo.close()
        os.environ.pop("API_TEST_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    sys.exit(main())
