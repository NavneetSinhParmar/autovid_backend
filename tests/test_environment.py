import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.environment import load_environment


class EnvironmentTests(unittest.TestCase):
    def test_process_then_local_then_legacy_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.local").write_text("SETTING=local\nLOCAL_ONLY=yes\n", encoding="utf-8")
            (root / ".env").write_text("SETTING=legacy\nFALLBACK=yes\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                load_environment(root)
                self.assertEqual(os.environ["SETTING"], "local")
                self.assertEqual(os.environ["FALLBACK"], "yes")
            with patch.dict(os.environ, {"SETTING": "deployment"}, clear=True):
                load_environment(root)
                self.assertEqual(os.environ["SETTING"], "deployment")
                self.assertEqual(os.environ["LOCAL_ONLY"], "yes")

    def test_missing_files_leave_environment_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"SETTING": "deployment"}, clear=True):
                load_environment(Path(directory))
                self.assertEqual(dict(os.environ), {"SETTING": "deployment"})
