import os
import subprocess
import shlex
from typing import Dict, Any, List


MEDIA_ROOT = os.getenv("MEDIA_ROOT", "./media")

FONT_PATH = "/usr/share/fonts/truetype/custom/Arial.ttf"

import uuid 
import re 
import urllib.parse 
import requests 
import hashlib 
import json 
from bson import ObjectId 
from app.db.connection import db 
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
    if path.startswith("/app/media"):
        return path

    path = path.replace("\\", "/")
    path = path.replace("./media/", "")
    path = path.replace("media/", "")
    path = path.lstrip("/")

    return os.path.join(MEDIA_ROOT, path)

def ensure_file_exists(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Media file not found: {path}")


# ---------------------------------------------------------
# FILTER COMPLEX GENERATOR (SAFE)
# ---------------------------------------------------------

def generate_filter_complex(template, canvas_w, canvas_h, duration):
    filters = []
    input_files = []

    # BASE CANVAS
    filters.append(
        f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base]"
    )

    last_video = "[base]"
    input_index = 0

    track_items = template.get("template_json", {}).get("trackItemsMap", {})

    for _, item in track_items.items():
        item_type = item["type"]
        display = item.get("display", {})
        details = item.get("details", {})

        start = float(display.get("from", 0))
        end = float(display.get("to", duration))
        dur = max(0.01, end - start)

        x = int(details.get("left", 0))
        y = int(details.get("top", 0))

        # ---------------- VIDEO ----------------
        if item_type == "video":
            src = abs_media_path(details["src"])
            input_files.append(src)
            idx = input_index
            input_index += 1

            filters.append(
                f"[{idx}:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
                f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"trim=duration={dur},setpts=PTS-STARTPTS[v{idx}]"
            )

            filters.append(
                f"{last_video}[v{idx}]overlay={x}:{y}:enable='between(t,{start},{end})'[base]"
            )

        # ---------------- IMAGE ----------------
        elif item_type == "image":
            src = abs_media_path(details["src"])
            input_files.append(src)
            idx = input_index
            input_index += 1

            filters.append(
                f"[{idx}:v]scale='min(iw,{canvas_w})':'min(ih,{canvas_h})',"
                f"setsar=1,tpad=stop_duration={dur}[img{idx}]"
            )

            filters.append(
                f"{last_video}[img{idx}]overlay={x}:{y}:enable='between(t,{start},{end})'[base]"
            )

        # ---------------- TEXT ----------------
        elif item_type == "text":
            text = details.get("text", "")
            size = int(details.get("fontSize", 48))
            color = details.get("color", "#ffffff")

            filters.append(
                f"{last_video}drawtext=text='{text}':"
                f"x={x}:y={y}:fontsize={size}:fontcolor={color}:"
                f"enable='between(t,{start},{end})'[base]"
            )

        # ---------------- AUDIO ----------------
        elif item_type == "audio":
            src = abs_media_path(details["src"])
            input_files.append(src)

    return ";".join(filters), input_files

# ---------------------------------------------------------
# MAIN RENDER FUNCTION
# ---------------------------------------------------------

def render_preview(template: dict, output_path: str):
    canvas = template.get("template_json", {}).get("canvas", {})
    canvas_w = int(canvas.get("width", 1920))
    canvas_h = int(canvas.get("height", 1080))
    duration = float(template.get("duration", 5))

    cmd = ["ffmpeg", "-y"]

    filter_complex, inputs = generate_filter_complex(
        template, canvas_w, canvas_h, duration
    )

    for f in inputs:
        cmd += ["-i", f]

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[base]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-movflags", "+faststart",
        "-t", str(duration),
        output_path
    ]

    print("FFMPEG CMD:\n", " ".join(cmd))

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        raise Exception(result.stderr)

    return output_path
