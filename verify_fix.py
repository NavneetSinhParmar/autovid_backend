import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from app.services.video_renderer import render_preview, FONT

print(f"DEBUG: FONT path being used: {FONT}")

# Mock template data
mock_template = {
    "template_json": {
        "design": {
            "size": {"width": 640, "height": 360},
            "fps": 30,
            "trackItemsMap": {
                "text_1": {
                    "type": "text",
                    "details": {
                        "text": "Verification Text",
                        "left": 100,
                        "top": 100,
                        "fontSize": 40,
                        "color": "#ffffff"
                    },
                    "display": {"from": 0, "to": 2000}
                }
            }
        },
        "duration": 2000
    }
}

output_path = "verify_output.mp4"

try:
    print("Starting render_preview...")
    render_preview(mock_template, output_path)
    print("Render finished.")
    if os.path.exists(output_path):
        print(f"SUCCESS: Output file created at {output_path}")
    else:
        print("FAILURE: Output file not found.")
except Exception as e:
    print(f"FAILURE: Exception occurred: {e}")
