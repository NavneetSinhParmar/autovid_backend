"""Small isolated image+text benchmark; no database or live queue writes."""
import json
import logging
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app.services.video_renderer import render_image_preview
from app.services.render_queue import current_render_temp_dir


def main():
    logging.getLogger("app").setLevel(logging.WARNING)
    with tempfile.TemporaryDirectory() as root:
        folder = Path(root)
        Image.new("RGBA", (600, 600), "#ff6020").save(folder / "logo.png")
        template = {"design": {"size": {"width": 1280, "height": 720},
            "trackItemIds": ["logo", "text"], "trackItemsMap": {
                "logo": {"type": "image", "details": {"src": str(folder / "logo.png"), "width": 180, "height": 180, "left": 50, "top": 50, "objectPosition": "left-top"}},
                "text": {"type": "text", "details": {"text": "Customer image preview", "fontSize": 48, "color": "#ffffff", "left": 300, "top": 300, "width": 850}},
            }}}
        elapsed = []
        with patch.dict(os.environ, {"RENDER_LOCK_DIR": str(folder / "locks")}), patch("app.services.video_renderer.normalize_media_src", side_effect=lambda value: value):
            token = current_render_temp_dir.set(root)
            try:
                for index in range(5):
                    output = folder / f"preview_{index}.jpg"
                    start = time.perf_counter()
                    render_image_preview(template, {}, {}, str(output))
                    elapsed.append(time.perf_counter() - start)
                    with Image.open(output) as image:
                        image.load()
                        assert image.size == (1280, 720)
                        assert any(high > 180 for low, high in image.crop((300, 300, 1150, 400)).getextrema()), "Text missing"
            finally:
                current_render_temp_dir.reset(token)
    result = {"scope": "local image renderer, not upload/API/queue time", "fixture": "1280x720 JPEG with PNG logo and text",
              "renders": 5, "elapsed_seconds": elapsed, "average_seconds": statistics.mean(elapsed), "maximum_seconds": max(elapsed)}
    Path("benchmark-image-local.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
