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

def parse_scale(transform_str: str) -> float:
    """
    Handles: 'scale(1)', 'scale(0.5, 0.5)', 'none'
    Returns: float (default 1.0)
    """
    if not transform_str or transform_str == "none":
        return 1.0
    try:
        # scale(0.32, 0.32) -> 0.32, 0.32
        inner = transform_str.replace("scale(", "").replace(")", "")
        # Split by comma and take the first value
        first_val = inner.split(",")[0].strip()
        return float(first_val)
    except Exception:
        return 1.0

def parse_px(value):
    """Handles '123.45px', numeric values, and list-like strings"""
    if isinstance(value, str):
        # Kuch cases mein value '0.32, 0.32' bhi aa sakti hai transform error ki wajah se
        clean_val = value.replace('px', '').split(',')[0].strip()
        try:
            return float(clean_val)
        except:
            return 0.0
    return float(value) if value is not None else 0.0


import re
import os
import subprocess

def safe_float(val):
    if val is None: return 0.0
    try:
        # '0.32, 0.32' ya '100px' jaise cases handle karne ke liye
        clean_val = str(val).replace("px", "").split(',')[0].strip()
        return float(clean_val)
    except:
        return 0.0

def render_preview(template, output_path):
    design = template.get("template_json", {}).get("design", {})
    track_items_map = design.get("trackItemsMap", {})
    tracks = design.get("tracks", [])
    duration = float(template.get("duration", 10))
    
    # JSON se size uthayein (Default 1920x1080)
    canvas_w = design.get("size", {}).get("width", 1920)
    canvas_h = design.get("size", {}).get("height", 1080)

    filter_parts = []
    visual_inputs = [] 
    audio_inputs = []  
    
    # 1. Base Black Canvas
    filter_parts.append(f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base]")
    last_label = "[base]"

    # 2. Inputs Collection
    for track in tracks:
        itype = track.get("type")
        for item_id in track.get("items", []):
            item = track_items_map.get(item_id, {})
            details = item.get("details", {})
            src = details.get("src", "").replace("./", "")
            if not src: continue

            if itype in ["video", "image"] or item.get("type") in ["video", "image"]:
                visual_inputs.append({"src": src, "item": item})
            elif itype == "audio":
                audio_inputs.append({"src": src, "item": item})

    # 3. Visual Layers (Videos/Images)
    for idx, data in enumerate(visual_inputs):
        item = data["item"]
        details = item.get("details", {})
        display = item.get("display", {})
        start, end = display.get("from", 0)/1000, display.get("to", duration*1000)/1000
        
        # Scale logic
        t_str = str(details.get("transform", "scale(1)"))
        scale_val = 1.0
        match = re.search(r"scale\(([^)]+)\)", t_str)
        if match: scale_val = safe_float(match.group(1))

        # JSON size * transform scale
        tw = int(safe_float(details.get("width", canvas_w)) * scale_val)
        th = int(safe_float(details.get("height", canvas_h)) * scale_val)
        left, top = safe_float(details.get("left", 0)), safe_float(details.get("top", 0))

        scaled, overlaid = f"sc{idx}", f"ov{idx}"
        
        # Filter: Pehle scale karo, phir background par overlay karo
        filter_parts.append(f"[{idx}:v]scale={tw}:{th},setpts=PTS-STARTPTS+{start}/TB[{scaled}]")
        filter_parts.append(f"{last_label}[{scaled}]overlay={left}:{top}:enable='between(t,{start},{end})'[{overlaid}]")
        last_label = f"[{overlaid}]"

    # 4. Text Layers (Always on top of video)
    txt_idx = 0
    for track in tracks:
        if track.get("type") == "text":
            for item_id in track.get("items", []):
                item = track_items_map.get(item_id, {})
                details, display = item.get("details", {}), item.get("display", {})
                start, end = display.get("from", 0)/1000, display.get("to", duration*1000)/1000
                
                text = details.get("text", "").replace("'", "\\'").replace(":", "\\:")
                x, y = safe_float(details.get("left", 0)), safe_float(details.get("top", 0))
                fs = int(safe_float(details.get("fontSize", 60)))
                color = details.get("color", "#ffffff").replace("#", "0x")
                
                # Font path fix
                font_path = os.path.abspath("app/Fonts/arial.ttf").replace("\\", "/").replace(":", "\\:")
                
                txt_label = f"tx{txt_idx}"
                # Drawtext application
                filter_parts.append(
                    f"{last_label}drawtext=fontfile='{font_path}':text='{text}':"
                    f"x={x}:y={y}:fontsize={fs}:fontcolor={color}:"
                    f"enable='between(t,{start},{end})'[{txt_label}]"
                )
                last_label = f"[{txt_label}]"
                txt_idx += 1

    # 5. Audio Mixing
    audio_filter = ""
    if audio_inputs:
        a_labels = ""
        for i in range(len(audio_inputs)):
            idx = len(visual_inputs) + i
            a_start = int(audio_inputs[i]["item"].get("display", {}).get("from", 0))
            a_labels += f"[{idx}:a]adelay={a_start}|{a_start}[aud{i}];"
        audio_filter = f"{a_labels}" + "".join([f"[aud{i}]" for i in range(len(audio_inputs))]) + f"amix=inputs={len(audio_inputs)}[outa]"

    # 6. Final Build & Run
    cmd = ["ffmpeg", "-y"]
    for v in visual_inputs:
        if v["src"].lower().endswith(('.jpg', '.jpeg', '.png')):
            cmd += ["-loop", "1", "-t", str(duration), "-i", v["src"]]
        else:
            cmd += ["-i", v["src"]]
    for a in audio_inputs:
        cmd += ["-i", a["src"]]

    if audio_filter:
        cmd += ["-filter_complex", ";".join(filter_parts) + ";" + audio_filter, "-map", last_label, "-map", "[outa]"]
    else:
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", last_label]

    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", str(duration), output_path]
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