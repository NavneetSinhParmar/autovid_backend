import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class AppImportTests(unittest.TestCase):
    def test_complete_application_imports_without_loading_torch(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; from app.main import app; assert 'torch' not in sys.modules; print('OK')"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "OK")

    def test_voiceover_health_preserves_device_response(self):
        from app.routes.voise_over import health
        for available in (True, False):
            with patch("app.routes.voise_over.cuda_available", return_value=available):
                self.assertEqual(health(), {"status": "ok", "cuda": available, "device": "cuda" if available else "cpu"})
