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
import shlex
from bson import ObjectId 
from app.db.connection import db 
from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
DEBUG = os.getenv("DEBUG", "False").lower() == "true" 

MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media")

print("📁 MEDIA_ROOT =", MEDIA_ROOT)

FFMPEG = "ffmpeg"

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
FONT_PATH = os.path.join(BASE_DIR, "Fonts", "arial.ttf")
FONT_PATH = FONT_PATH.replace("\\", "/")
PX_RE = re.compile(r"-?\d+(\.\d+)?")

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def abs_media_path(path: str) -> str:
    print("🔍 abs_media_path input:", path)

    path = path.replace("\\", "/")

    if path.startswith("http"):
        raise ValueError("Remote URLs not supported")

    path = path.replace("./media/", "")
    path = path.replace("media/", "")
    path = path.lstrip("/")

    full_path = os.path.join(MEDIA_ROOT, path)

    print("✅ abs_media_path resolved:", full_path)
    return full_path

def ensure_file_exists(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Media file not found: {path}")

def parse_position(value):
    """
    Convert position value to float:
    - Handles '123.45px', '-1375.5px', or numeric values
    - Returns float
    """
    if isinstance(value, str):
        value = value.strip().replace("px", "")
    try:
        return float(value)
    except Exception:
        return 0.0

def parse_px(value):
    """Convert '123.45px' or '-1375.5px' to float/int"""
    if isinstance(value, str):
        return float(value.replace('px', ''))
    return float(value)

def escape_text(text):
    return text.replace("'", r"\'").replace(":", r"\:")

def ffmpeg_escape_path(path: str) -> str:
    # Windows-safe FFmpeg path
    return path.replace("\\", "/").replace(":", "\\:")

def ffmpeg_escape_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
    )




# ---------------------------------------------------------
# MAIN RENDER FUNCTION
# ---------------------------------------------------------

def render_video(task_id: str):
    task = db.video_tasks.find_one({"_id": ObjectId(task_id)})
    template = db.templates.find_one({"_id": ObjectId(task["template_id"])})
    customer = db.customers.find_one({"_id": ObjectId(task["customer_id"])})

    base_video = abs_media_path(template["base_video_url"])
    ensure_file_exists(base_video)

    text = customer["full_name"]

    output_path = os.path.join(MEDIA_ROOT, f"{task_id}.mp4")

    vf = (
        f"drawtext="
        f"fontfile={FONT_PATH}:"
        f"text='{escape_text(text)}':"
        f"x=200:y=300:"
        f"fontsize=40:"
        f"fontcolor=white"
    )

    cmd = [
        FFMPEG,
        "-y",
        "-i", base_video,
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        output_path
    ]

    print("🎬 SIMPLE CMD:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    return output_path


def generate_ffmpeg_cmd(template):
    design = template['template_json']['design']
    track_map = design['trackItemsMap']
    duration = template.get('duration', 10)
    
    filter_parts = []
    input_files = []
    map_audio = []
    
    # 1️⃣ Base black canvas
    filter_parts.append(f"color=c=black:s=1920x1080:d={duration}[base];")
    last_label = "[base]"
    
    # 2️⃣ Process all video items
    video_labels = []
    for idx, vid_id in enumerate([tid for tid in design['trackItemIds'] if track_map[tid]['type']=='video']):
        item = track_map[vid_id]
        path = item['details']['src']
        input_files.append(path)
        start = item.get('display', {}).get('from', 0)/1000
        end = item.get('display', {}).get('to', duration*1000)/1000
        scale_factor = float(item['details'].get('transform', 'scale(1)')[6:-1]) if 'transform' in item['details'] else 1.0
        filter_parts.append(f"[{idx}:v]scale=1920*{scale_factor}:1080*{scale_factor},setpts=PTS-STARTPTS[v{idx}];")
        filter_parts.append(f"{last_label}[v{idx}]overlay=0:0:enable='between(t,{start},{end})'[o{idx}];")
        last_label = f"[o{idx}]"
        video_labels.append(last_label)
    
    # 3️⃣ Process all text items
    text_items = [tid for tid in design['trackItemIds'] if track_map[tid]['type']=='text']
    for idx, txt_id in enumerate(text_items):
        item = track_map[txt_id]
        text = item['details']['text'].replace("'", "\\'")
        x = int(float(item['details'].get('left', 0)))
        y = int(float(item['details'].get('top', 0)))
        fontsize = item['details'].get('fontSize', 60)
        color = item['details'].get('color', '#FFFFFF').replace('#','0x')
        start = item['display']['from']/1000
        end = item['display']['to']/1000
        filter_parts.append(
            f"{last_label}drawtext=fontfile=D:/MyProjects/freelencing/Video_Generater/autovid_backend/app/Fonts/arial.ttf:"
            f"text='{text}':x={x}:y={y}:fontsize={fontsize}:fontcolor={color}:enable='between(t,{start},{end})'[txt{idx}];"
        )
        last_label = f"[txt{idx}]"
    
    # 4️⃣ Process all image items
    image_items = [tid for tid in design['trackItemIds'] if track_map[tid]['type']=='image']
    for idx, img_id in enumerate(image_items):
        item = track_map[img_id]
        path = item['details']['src']
        input_files.append(path)
        start = item['display']['from']/1000
        end = item['display']['to']/1000
        scale_x = item['details'].get('transform', 'scale(1)')[6:-1] if 'transform' in item['details'] else 1
        x = int(item['details'].get('left', 0))
        y = int(item['details'].get('top', 0))
        filter_parts.append(f"[{len(video_labels)+idx}:v]scale=iw*{scale_x}:ih*{scale_x},setpts=PTS-STARTPTS[vimg{idx}];")
        filter_parts.append(f"{last_label}[vimg{idx}]overlay={x}:{y}:enable='between(t,{start},{end})'[oimg{idx}];")
        last_label = f"[oimg{idx}]"
    
    # 5️⃣ Audio items
    audio_items = [tid for tid in design['trackItemIds'] if track_map[tid]['type']=='audio']
    for idx, aud_id in enumerate(audio_items):
        item = track_map[aud_id]
        path = item['details']['src']
        input_files.append(path)
        map_audio.append(f"-map {len(video_labels)+len(image_items)+idx}:a")
    
    # Combine filter complex
    filter_complex = "".join(filter_parts).rstrip(';')
    
    # Final FFmpeg command
    cmd = ["ffmpeg", "-y"]
    for f in input_files:
        cmd += ["-i", f]
    cmd += ["-filter_complex", filter_complex]
    cmd += map_audio
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(design.get('fps',30))]
    cmd += ["-t", str(duration), "output_preview.mp4"]
    
    # Return safe shell command
    return " ".join(shlex.quote(c) for c in cmd)

def render_preview(template, output_path):
    """
    Render preview video from template_json (trackItemsMap based)
    Supports: video, image, text, audio
    """

    design = template.get("template_json", {}).get("design", {})
    tracks = design.get("tracks", [])
    track_items_map = design.get("trackItemsMap", {})
    duration = float(template.get("duration", 10))

    filter_parts = []
    input_files = []
    last_label = "[base]"
    audio_input_index = None

    # counters
    v_count = 0
    img_count = 0
    txt_count = 0

    # -------------------------------------------------
    # 1️⃣ BASE CANVAS
    # -------------------------------------------------
    filter_parts.append(
        f"color=c=black:s=1920x1080:d={duration}[base];"
    )

    # -------------------------------------------------
    # 2️⃣ PROCESS TRACKS (ORDER MATTERS)
    # -------------------------------------------------
    for track in tracks:
        track_type = track.get("type")
        for item_id in track.get("items", []):
            item = track_items_map.get(item_id, {})
            details = item.get("details", {})
            display = item.get("display", {})

            start = display.get("from", 0) / 1000
            end = display.get("to", duration * 1000) / 1000

            # ---------------- VIDEO ----------------
            if track_type == "video":
                src = details.get("src")
                abs_src = abs_media_path(src)
                ensure_file_exists(abs_src)
                input_files.append(abs_src)

                if not abs_src:
                    continue

                idx = len(input_files) - 1

                v_label = f"[v{v_count}]"
                o_label = f"[ov{v_count}]"

                filter_parts.append(
                    f"[{idx}:v]scale=1920:1080,setpts=PTS-STARTPTS{v_label};"
                )
                filter_parts.append(
                    f"{last_label}{v_label}"
                    f"overlay=0:0:enable='between(t,{start},{end})'"
                    f"{o_label};"
                )

                last_label = o_label
                v_count += 1

            # ---------------- IMAGE ----------------
            elif track_type == "image":
                src = details.get("src")
                abs_src = abs_media_path(src)
                ensure_file_exists(abs_src)
                input_files.append(abs_src)

                if not abs_src:
                    continue

                idx = len(input_files) - 1

                left = int(parse_px(details.get("left", 0)))
                top = int(parse_px(details.get("top", 0)))

                v_label = f"[img{img_count}]"
                o_label = f"[oimg{img_count}]"

                filter_parts.append(
                    f"[{idx}:v]scale=iw:ih,setpts=PTS-STARTPTS{v_label};"
                )
                filter_parts.append(
                    f"{last_label}{v_label}"
                    f"overlay={left}:{top}:enable='between(t,{start},{end})'"
                    f"{o_label};"
                )

                last_label = o_label
                img_count += 1

            # ---------------- TEXT ----------------
            elif track_type == "text":
                text = details.get("text", "")
                text = ffmpeg_escape_text(text)

                left = int(parse_px(details.get("left", 0)))
                top = int(parse_px(details.get("top", 0)))
                fontsize = int(details.get("fontSize", 48))

                t_label = f"[txt{txt_count}]"

                filter_parts.append(
                    f"{last_label}"
                    f"drawtext="
                    f"fontfile='{ffmpeg_escape_path(FONT_PATH)}':"
                    f"text='{text}':"
                    f"x={left}:y={top}:"
                    f"fontsize={fontsize}:"
                    f"fontcolor=white:"
                    f"enable='between(t,{start},{end})'"
                    f"{t_label};"
                )

                last_label = t_label
                txt_count += 1

            # ---------------- AUDIO ----------------
            elif track_type == "audio":
                src = details.get("src")
                abs_src = abs_media_path(src)
                ensure_file_exists(abs_src)
                input_files.append(abs_src)
                audio_input_index = len(input_files) - 1

                if not abs_src:
                    continue

    # -------------------------------------------------
    # 3️⃣ BUILD FFMPEG COMMAND
    # -------------------------------------------------
    filter_complex = "".join(filter_parts).rstrip(";")

    cmd = ["ffmpeg", "-y"]

    for f in input_files:
        cmd += ["-i", f]

    cmd += ["-filter_complex", filter_complex]

    # 🎯 VERY IMPORTANT: MAP FINAL VIDEO
    cmd += ["-map", last_label]

    # 🎵 MAP AUDIO IF EXISTS
    if audio_input_index is not None:
        cmd += ["-map", f"{audio_input_index}:a"]

    cmd += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-t", str(duration),
        output_path
    ]

    print("\n🎬 FFMPEG CMD:\n", " ".join(cmd), "\n")

    subprocess.run(cmd, check=True)
    print("✅ Preview rendered successfully:", output_path)