import json
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.video_renderer import render_preview, abs_media_path

def test_render():
    template_path = "template.json"
    output_path = "output_test.mp4"
    
    if os.path.exists(output_path):
        os.remove(output_path)
        
    with open(template_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # The structure in template.json seems to have a root key "template"
    # But render_preview expects the dict that contains "template_json"
    # wrapper.
    
    template_data = data.get("template", data)
    
    print("Testing render_preview...")
    try:
        result = render_preview(template_data, output_path)
        print(f"Render completed: {output_path}")
    except Exception as e:
        print(f"Render failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_render()
