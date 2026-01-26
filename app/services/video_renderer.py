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
import copy
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
PX_RE = re.compile(r"-?\d+(\.\d+)?")

def abs_media_path(path: str) -> str:
    path = path.replace("\\", "/")
    path = path.replace("./media/", "").replace("media/", "").lstrip("/")
    full_path = os.path.join(MEDIA_ROOT, path)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Media file not found: {full_path}")
    return full_path

def parse_px(value):
    if isinstance(value, str):
        return float(value.replace("px",""))
    return float(value)

def ffmpeg_escape_text(text: str):
    return text.replace("\\","\\\\").replace(":","\\:").replace("'","\\'")

def ffmpeg_escape_path(path: str):
    return path.replace("\\","/").replace(":", "\\:")

def replace_placeholders(template_json: dict, customer: dict) -> dict:
    template_str = json.dumps(template_json)
    for key, value in customer.items():
        placeholder = f"{{{{{key}}}}}"
        template_str = template_str.replace(placeholder, str(value))
    return json.loads(template_str)

def render_preview(template_json: dict, customer: dict, output_path: str):
    design = template_json.get("design", {})
    track_map = design.get("trackItemsMap", {})
    tracks = design.get("tracks", [])
    duration = design.get("duration", template_json.get("options", {}).get("duration", 10))
    width = design.get("size", {}).get("width", 1920)
    height = design.get("size", {}).get("height", 1080)
    fps = design.get("fps", 30)

    filter_parts = []
    input_files = []
    last_label = "[base]"

    # Base Layer
    filter_parts.append(f"color=c=black:s={width}x{height}:d={duration}[base];")

    # Video/Image Layer
    idx_counter = 0
    for track in tracks:
        if track["type"] in ["video", "image"]:
            for item_id in track.get("items", []):
                item = track_map[item_id]
                src = abs_media_path(item["details"]["src"])
                input_files.append(src)
                idx = len(input_files)-1

                start = item.get("display", {}).get("from", 0)/1000
                end = item.get("display", {}).get("to", duration*1000)/1000
                scale = float(item["details"].get("transform","scale(1)")[6:-1]) if "transform" in item["details"] else 1
                x = parse_px(item["details"].get("left",0))
                y = parse_px(item["details"].get("top",0))

                v_label = f"[v{idx_counter}]"
                o_label = f"[ov{idx_counter}]"

                # Scale video/image
                filter_parts.append(f"[{idx}:v]scale=iw*{scale}:ih*{scale},setpts=PTS-STARTPTS{v_label};")
                filter_parts.append(f"{last_label}{v_label}overlay={x}:{y}:enable='between(t,{start},{end})'{o_label};")
                last_label = o_label
                idx_counter += 1

    # Text Layer
    txt_counter = 0
    for track in tracks:
        if track["type"]=="text":
            for item_id in track.get("items", []):
                item = track_map[item_id]
                text = item["details"].get("text","")
                if customer:
                    text = replace_placeholders({"text": text}, customer)["text"]

                text = ffmpeg_escape_text(text)
                x = parse_px(item["details"].get("left",0))
                y = parse_px(item["details"].get("top",0))
                fontsize = int(item["details"].get("fontSize",48))
                color = item["details"].get("color","#ffffff").replace("#","0x")
                start = item.get("display",{}).get("from",0)/1000
                end = item.get("display",{}).get("to", duration*1000)/1000

                t_label = f"[txt{txt_counter}]"
                filter_parts.append(
                    f"{last_label}drawtext=fontfile='{ffmpeg_escape_path(FONT_PATH)}':"
                    f"text='{text}':x={x}:y={y}:fontsize={fontsize}:fontcolor={color}:"
                    f"enable='between(t,{start},{end})'{t_label};"
                )
                last_label = t_label
                txt_counter += 1

    # Audio Layer
    audio_idx = None
    for track in tracks:
        if track["type"]=="audio":
            for item_id in track.get("items",[]):
                src = abs_media_path(track_map[item_id]["details"]["src"])
                input_files.append(src)
                audio_idx = len(input_files)-1

    # Build final FFmpeg command
    cmd = ["ffmpeg", "-y"]
    for f in input_files: cmd += ["-i", f]
    cmd += ["-filter_complex", "".join(filter_parts).rstrip(";")]
    cmd += ["-map", last_label]
    if audio_idx is not None: cmd += ["-map", f"{audio_idx}:a"]
    cmd += ["-c:v","libx264","-pix_fmt","yuv420p","-r",str(fps),"-t",str(duration), output_path]

    subprocess.run(cmd, check=True)
    
            
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

