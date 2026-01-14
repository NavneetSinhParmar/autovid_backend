import os
import subprocess
import shlex
from typing import Dict, Any, List


MEDIA_ROOT = "/app/media"
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
MEDIA_ROOT = "media/generated" 
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
    """
    Converts:
      ./media/xxx.mp4
      media/xxx.mp4
      /media/xxx.mp4
    into:
      /app/media/xxx.mp4
    """
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

def generate_filter_complex(
    template: Dict[str, Any],
    canvas_w: int,
    canvas_h: int,
    duration: float
):
    filters: List[str] = []
    input_files: List[str] = []

    # ---------- BASE ----------
    filters.append(
        f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base]"
    )

    input_index = 0
    last_video_label = "[base]"

    track_items = template.get("trackItemsMap", {})

    for _, item in track_items.items():
        item_type = item.get("type")
        display = item.get("display", {})
        details = item.get("details", {})

        start = float(display.get("from", 0))
        end = float(display.get("to", duration))
        dur = max(0.01, end - start)

        src = details.get("src")
        if not src:
            continue

        src_path = abs_media_path(src)
        ensure_file_exists(src_path)

        input_files.append(src_path)
        idx = input_index
        input_index += 1

        x = int(details.get("left", 0))
        y = int(details.get("top", 0))

        # ---------- VIDEO ----------
        if item_type == "video":
            vlabel = f"[v{idx}]"

            filters.append(
                f"[{idx}:v]"
                f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
                f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"trim=duration={dur},setpts=PTS-STARTPTS"
                f"{vlabel}"
            )

            filters.append(
                f"{last_video_label}{vlabel}"
                f"overlay={x}:{y}:enable='between(t,{start},{end})'"
                f"[base]"
            )

            last_video_label = "[base]"

        # ---------- IMAGE ----------
        elif item_type == "image":
            ilabel = f"[img{idx}]"

            filters.append(
                f"[{idx}:v]"
                f"scale='min(iw,{canvas_w})':'min(ih,{canvas_h})',"
                f"setsar=1,"
                f"tpad=stop_mode=clone:stop_duration={dur},"
                f"format=rgba"
                f"{ilabel}"
            )

            filters.append(
                f"{last_video_label}{ilabel}"
                f"overlay={x}:{y}:enable='between(t,{start},{end})'"
                f"[base]"
            )

            last_video_label = "[base]"

        # ---------- TEXT ----------
        elif item_type == "text":
            text = details.get("text", "")
            size = int(details.get("fontSize", 48))
            color = details.get("color", "#ffffff")

            filters.append(
                f"{last_video_label}"
                f"drawtext=fontfile='{FONT_PATH}':"
                f"text='{text}':"
                f"x={x}:y={y}:"
                f"fontsize={size}:"
                f"fontcolor={color}:"
                f"enable='between(t,{start},{end})'"
                f"[base]"
            )

            last_video_label = "[base]"

        # ---------- AUDIO ----------
        elif item_type == "audio":
            alabel = f"[a{idx}]"

            filters.append(
                f"[{idx}:a]"
                f"atrim=duration={duration},"
                f"asetpts=PTS-STARTPTS"
                f"{alabel}"
            )

    return ";".join(filters), input_files


# ---------------------------------------------------------
# MAIN RENDER FUNCTION
# ---------------------------------------------------------

def render_preview(
    template: Dict[str, Any],
    output_path: str
):
    canvas = template.get("canvas", {})
    canvas_w = int(canvas.get("width", 1920))
    canvas_h = int(canvas.get("height", 1080))
    duration = float(template.get("duration", 5))

    base_video_url = template.get("base_video_url")
    base_audio_url = template.get("base_audio_url")

    cmd = ["ffmpeg", "-y"]

    # ---------- BASE VIDEO ----------
    if base_video_url:
        base_video_path = abs_media_path(base_video_url)
        ensure_file_exists(base_video_path)
        cmd += ["-i", base_video_path]
        base_video_index = 0
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}"]
        base_video_index = 0

    # ---------- BASE AUDIO ----------
    if base_audio_url:
        base_audio_path = abs_media_path(base_audio_url)
        ensure_file_exists(base_audio_path)
        cmd += ["-i", base_audio_path]

    # ---------- FILTER COMPLEX ----------
    filter_complex, overlay_inputs = generate_filter_complex(
        template,
        canvas_w,
        canvas_h,
        duration
    )

    for f in overlay_inputs:
        cmd += ["-i", f]

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[base]",
    ]

    if base_audio_url:
        cmd += ["-map", "1:a"]

    cmd += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-movflags", "+faststart",
        "-threads", "2",
        "-t", str(duration),
        output_path
    ]

    print("FFMPEG CMD:\n", " ".join(shlex.quote(x) for x in cmd))

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise Exception(
            f"FFmpeg failed ({result.returncode}):\n{result.stderr[:1500]}"
        )

    return output_path
