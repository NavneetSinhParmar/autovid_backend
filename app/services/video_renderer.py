import os
import subprocess
import shlex
from typing import Dict, Any, List
import uuid 
import re 
import urllib.parse 
import requests 
import hashlib 
import json 
from bson import ObjectId 
from app.db.connection import db 


MEDIA_ROOT = os.getenv("MEDIA_ROOT", "./media")

FONT_PATH = "/usr/share/fonts/truetype/custom/Arial.ttf"

DEBUG = os.getenv("DEBUG", "False").lower() == "true" 

def render_video(task_id: str): 
    task = db.video_tasks.find_one({"_id": ObjectId(task_id)}) 
    template = db.templates.find_one({"_id": ObjectId(task["template_id"])}) 
    customer = db.customers.find_one({"_id": ObjectId(task["customer_id"])}) 
    template_json = template["template_json"] 
    base_video = template["base_video_url"] 
    os.makedirs(MEDIA_ROOT, exist_ok=True) 
    output_path = f"{MEDIA_ROOT}/{task_id}.mp4" # 👉 SIMPLE TEXT OVERLAY (extend later) 
    text_layer = template_json["layers"][0] 
    text = text_layer["text"].replace( "{{full_name}}", 
    customer["full_name"] ) 
    cmd = [ FFMPEG, "-y", "-i", base_video, "-vf", f"drawtext=text='{text}':x=200:y=300:fontsize=40:fontcolor=white", output_path ] 
    subprocess.run(cmd, check=True) 
    return output_path
# ---------------------------------------------------------
# UTILS
# ---------------------------------------------------------

def abs_media_path(path: str) -> str:
    print("abs_media_path input:", path)  # 🔹 debug
    if path.startswith("/app/media"):
        return path

    path = path.replace("\\", "/")
    path = path.replace("./media/", "")
    path = path.replace("media/", "")
    path = path.lstrip("/")

    full_path = os.path.join(MEDIA_ROOT, path)
    print("abs_media_path resolved:", full_path)  # 🔹 debug
    return full_path

def ensure_file_exists(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Media file not found: {path}")


# ---------------------------------------------------------
# FILTER COMPLEX GENERATOR (SAFE)
# ---------------------------------------------------------
def px_to_int(value, default=0):
    """
    Converts '123px' or '123.45px' or int/float to int
    """
    if value is None:
        return default

    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        value = value.replace("px", "").strip()
        try:
            return int(float(value))
        except ValueError:
            return default

    return default


PX_RE = re.compile(r"-?\d+(\.\d+)?")

def parse_px(val, default=0):
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return int(val)
    m = PX_RE.search(str(val))
    return int(float(m.group())) if m else default


def generate_filter_complex(template, canvas_w, canvas_h, duration):
    print("___________________Inside Filter Complex___________________")

    filters = []
    input_files = []

    # base canvas
    filters.append(
        f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base]"
    )
    last_video = "[base]"
    input_idx = 0
    audio_idx = None

    track_items = template.get("template_json", {}).get("design", {}).get("trackItemsMap", {})
    print("Track Items Count:", len(track_items))

    for item_id, item in track_items.items():
        item_type = item.get("type")
        details = item.get("details", {})
        display = item.get("display", {})

        src = details.get("src")
        print(f"ITEM: {item_id} TYPE: {item_type} SRC: {src}")

        start = (display.get("from", 0)) / 1000
        end = (display.get("to", duration * 1000)) / 1000

        x = parse_px(details.get("left", 0))
        y = parse_px(details.get("top", 0))

        if item_type in ("video", "image") and src:
            abs_path = os.path.abspath(src)
            print("Resolved path:", abs_path)

            if not os.path.exists(abs_path):
                print("❌ FILE NOT FOUND:", abs_path)
                continue

            input_files.append(abs_path)

            # scale
            if item_type == "video":
                filters.append(
                    f"[{input_idx}:v]scale={canvas_w}:{canvas_h}[v{input_idx}]"
                )
            else:
                filters.append(
                    f"[{input_idx}:v]scale=iw:ih[v{input_idx}]"
                )

            # overlay
            filters.append(
                f"{last_video}[v{input_idx}]overlay={x}:{y}:enable='between(t,{start},{end})'[out{input_idx}]"
            )

            last_video = f"[out{input_idx}]"
            input_idx += 1

        elif item_type == "audio" and src:
            abs_path = os.path.abspath(src)
            print("Resolved audio:", abs_path)

            if not os.path.exists(abs_path):
                print("❌ AUDIO NOT FOUND:", abs_path)
                continue

            input_files.append(abs_path)
            audio_idx = input_idx
            input_idx += 1

        elif item_type == "text":
            print("📝 TEXT FOUND (not rendered yet):", details.get("text"))

    filter_complex = ";".join(filters)

    print("\nInput files:")
    for f in input_files:
        print(" ", f)

    print("\nFILTER_COMPLEX:\n", filter_complex)

    return filter_complex, input_files, last_video, audio_idx

# ---------------------------------------------------------
# MAIN RENDER FUNCTION
# ---------------------------------------------------------

import subprocess

def render_preview(template, output_path):
    design = template.get("template_json", {}).get("design", {})
    size = design.get("size", {})

    canvas_w = size.get("width", 1920)
    canvas_h = size.get("height", 1080)
    duration = template.get("duration", 5)

    print(f"Canvas: {canvas_w} x {canvas_h} Duration: {duration}")

    filter_complex, input_files, last_video, audio_idx = generate_filter_complex(
        template, canvas_w, canvas_h, duration
    )

    cmd = ["ffmpeg", "-y"]

    for f in input_files:
        cmd += ["-i", f]

    cmd += [
        "-filter_complex", filter_complex,
        "-map", last_video,
    ]

    if audio_idx is not None:
        cmd += ["-map", f"{audio_idx}:a"]

    cmd += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-movflags", "+faststart",
        "-t", str(duration),
        output_path
    ]

    print("\nFFMPEG CMD:\n", " ".join(cmd))

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        print("❌ FFmpeg ERROR:")
        print(result.stderr)
        raise Exception("FFmpeg failed")

    print("✅ Render complete:", output_path)
