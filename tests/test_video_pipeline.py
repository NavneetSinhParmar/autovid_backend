import json
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image

from app.services.video_renderer import render_preview
from app.services.output_validator import validate_generated_video
from app.services.render_queue import current_render_temp_dir


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VideoPipelineTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        locks = tempfile.TemporaryDirectory()
        self.addCleanup(locks.cleanup)
        config = patch.dict("os.environ", {"RENDER_LOCK_DIR": locks.name})
        config.start()
        self.addCleanup(config.stop)

    def test_high_fps_video_keeps_timeline_audio_and_output_frame_rate(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.mp4"
            output = Path(root) / "output.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=red:s=64x36:r=60:d=1", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=1", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
            ], check=True)
            template = {"duration": 2, "template_json": {"design": {
                "size": {"width": 64, "height": 36}, "fps": 15,
                "trackItemIds": ["video"], "trackItemsMap": {"video": {
                    "type": "video", "details": {
                        "src": str(source), "width": 64, "height": 36,
                    }, "display": {"from": 500, "to": 1500},
                }},
            }}}
            with patch("app.services.video_renderer.normalize_media_src", side_effect=lambda value: value):
                render_preview(template, {}, str(output))
            metadata = validate_generated_video(str(output))
            self.assertAlmostEqual(metadata["duration"], 2, places=1)
            self.assertEqual(metadata["audio_codec"], "aac")
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate,nb_frames", "-of", "json", str(output),
            ], capture_output=True, text=True, check=True)
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual(stream["avg_frame_rate"], "15/1")
            self.assertEqual(int(stream["nb_frames"]), 30)
            for timestamp, red in [(0.2, False), (0.8, True), (1.8, False)]:
                frame = subprocess.run([
                    "ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(output),
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
                ], capture_output=True, check=True).stdout
                pixel = frame[(18 * 64 + 32) * 3: (18 * 64 + 32) * 3 + 3]
                self.assertEqual(pixel[0] > 180 and pixel[1] < 40, red)

    def test_simultaneous_image_and_video_have_separate_outputs(self):
        from unittest.mock import patch
        from app.services.video_renderer import render_image_preview
        from app.services import render_resources
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            template = {"duration": 1, "template_json": {"design": {
                "size": {"width": 64, "height": 36}, "trackItemIds": [], "trackItemsMap": {},
            }}}
            for name in ("image", "video"):
                (folder / name).mkdir()
            def image():
                token = current_render_temp_dir.set(str(folder / "image"))
                try:
                    render_image_preview(template["template_json"], {}, {}, str(folder / "image" / "output.jpg"))
                finally:
                    current_render_temp_dir.reset(token)
            def video():
                token = current_render_temp_dir.set(str(folder / "video"))
                try:
                    render_preview(template, {}, str(folder / "video" / "output.mp4"))
                finally:
                    current_render_temp_dir.reset(token)
            with patch.dict("os.environ", {"RENDER_LOCK_DIR": str(folder / "locks")}), patch.object(render_resources, "available_memory_mb", return_value=100000), patch.object(render_resources, "settings", replace(render_resources.settings, max_concurrent_video_renders=2)), ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(image), pool.submit(video)]
                for future in futures:
                    future.result(timeout=30)
            self.assertTrue((folder / "image" / "output.jpg").is_file())
            self.assertEqual(validate_generated_video(str(folder / "video" / "output.mp4"))["duration"], 1)

    def test_single_still_frame_repeats_only_during_its_display_interval(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            image = folder / "image.png"
            Image.new("RGB", (64, 36), "red").save(image)
            output = folder / "video.mp4"
            template = {"duration": 1.5, "template_json": {"design": {
                "size": {"width": 64, "height": 36}, "fps": 30,
                "trackItemIds": ["image"], "trackItemsMap": {"image": {
                    "type": "image", "details": {"src": str(image), "width": 64, "height": 36},
                    "display": {"from": 500, "to": 1000},
                }},
            }}}
            # The source resolver normally receives media paths; use a remote-free absolute source.
            from unittest.mock import patch
            with patch("app.services.video_renderer.normalize_media_src", side_effect=lambda value: value):
                render_preview(template, {}, str(output))
            metadata = validate_generated_video(str(output))
            self.assertAlmostEqual(metadata["duration"], 1.5, places=1)
            for timestamp, red in [(0.2, False), (0.8, True), (1.3, False)]:
                frame = subprocess.run([
                    "ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(output),
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
                ], capture_output=True, check=True).stdout
                pixel = frame[(18 * 64 + 32) * 3: (18 * 64 + 32) * 3 + 3]
                self.assertEqual(pixel[0] > 180 and pixel[1] < 40, red)

    def test_1080p_geometry_and_audio_survive_output_size_composition(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            image = folder / "image.png"
            Image.new("RGB", (100, 100), "red").save(image)
            audio = folder / "audio.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio)], check=True)
            output = folder / "output.mp4"
            template = {"duration": 1, "template_json": {"design": {
                "size": {"width": 1920, "height": 1080}, "fps": 30,
                "trackItemIds": ["image", "audio"], "trackItemsMap": {
                    "image": {"type": "image", "details": {"src": str(image), "width": 300, "height": 300, "left": 960, "top": 540, "objectPosition": "left-top"}},
                    "audio": {"type": "audio", "details": {"src": str(audio)}, "display": {"from": 0, "to": 1000}},
                },
            }}}
            from unittest.mock import patch
            with patch("app.services.video_renderer.normalize_media_src", side_effect=lambda value: value):
                render_preview(template, {}, str(output))
            metadata = validate_generated_video(str(output))
            self.assertEqual((metadata["width"], metadata["height"], metadata["audio_codec"]), (1280, 720, "aac"))
            self.assertEqual(template["template_json"]["design"]["trackItemsMap"]["image"]["details"]["left"], 960)
            frame = subprocess.run([
                "ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(output),
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ], capture_output=True, check=True).stdout
            pixel = frame[(400 * 1280 + 700) * 3: (400 * 1280 + 700) * 3 + 3]
            self.assertGreater(pixel[0], 180)
            self.assertLess(pixel[1], 40)
