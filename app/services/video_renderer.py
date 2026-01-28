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

import textwrap

def wrap_text(text, width):
    """FFmpeg doesn't wrap text, so we manually insert newlines."""
    if not text: return ""
    # 600px width par 120 fontsize ke liye approx 10-15 chars aate hain
    # Aap isko calculate bhi kar sakte hain: (width / (fontsize * 0.6))
    wrapper = textwrap.TextWrapper(width=20) 
    return "\n".join(wrapper.wrap(text))

def render_preview(template, output_path):
    design = template.get("template_json", {}).get("design", {})
    track_items_map = design.get("trackItemsMap", {})
    duration = float(template.get("duration", 10))
    
    canvas_w = design.get("size", {}).get("width", 1920)
    canvas_h = design.get("size", {}).get("height", 1080)

    filter_parts = []
    input_files = []
    
    # 1. Base Canvas (Sabse niche ki layer)
    filter_parts.append(f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base]")
    last_label = "[base]"

    v_img_count = 0
    txt_count = 0
    visual_inputs = [] # Video/Image input indices track karne ke liye

    # trackItemIds se order maintain hota hai (Z-index)
    for item_id in design.get("trackItemIds", []):
        item = track_items_map.get(item_id, {})
        details = item.get("details", {})
        display = item.get("display", {})
        
        start = display.get("from", 0) / 1000
        end = display.get("to", duration * 1000) / 1000

        # --- PHASE 1: VIDEO & IMAGE ---
        if item.get("type") in ["video", "image"]:
            abs_src = abs_media_path(details.get("src"))
            ensure_file_exists(abs_src)
            input_files.append(abs_src)
            
            curr_input_idx = len(input_files) - 1
            
            # Scaling logic
            transform_str = details.get("transform", "scale(1)")
            scale_val = 1.0
            if "scale" in transform_str:
                try:
                    match = re.search(r"scale\((.*?)\)", transform_str)
                    scale_val = float(match.group(1)) if match else 1.0
                except: scale_val = 1.0

            target_w = int(float(details.get("width", canvas_w)) * scale_val)
            target_h = int(float(details.get("height", canvas_h)) * scale_val)
            
            left = int(parse_px(details.get("left", 0)))
            top = int(parse_px(details.get("top", 0)))

            # Labels for this specific layer
            scaled_label = f"scaled{v_img_count}"
            overlaid_label = f"ovl{v_img_count}"
            
            # Important: Agar video hai toh [idx:v] use karo, agar image hai toh bhi [idx:v] FFmpeg images ke liye bhi chalta hai
            # 1. Scale input
            filter_parts.append(f"[{curr_input_idx}:v]scale={target_w}:{target_h},setpts=PTS-STARTPTS[{scaled_label}]")
            # 2. Overlay onto the PREVIOUS result
            filter_parts.append(f"{last_label}[{scaled_label}]overlay={left}:{top}:enable='between(t,{start},{end})'[{overlaid_label}]")
            
            # Agle item ke liye ye base ban jayega
            last_label = f"[{overlaid_label}]"
            v_img_count += 1

        # --- PHASE 2: TEXT ---
        elif item.get("type") == "text":
            raw_text = details.get("text", "")
            # Simple word wrap logic (Every 30 chars a new line)
            wrapped_text = "\n".join(re.findall(r'.{1,30}(?:\s+|$)', raw_text))
            text = ffmpeg_escape_text(wrapped_text)
            
            left = int(parse_px(details.get("left", 0)))
            top = int(parse_px(details.get("top", 0)))
            fontsize = int(details.get("fontSize", 48))
            color = details.get("color", "#ffffff").replace("#", "0x")
            
            t_label = f"text_layer{txt_count}"
            filter_parts.append(
                f"{last_label}drawtext=fontfile='{ffmpeg_escape_path(FONT_PATH)}':"
                f"text='{text}':x={left}:y={top}:fontsize={fontsize}:fontcolor={color}:"
                f"enable='between(t,{start},{end})'[{t_label}]"
            )
            last_label = f"[{t_label}]"
            txt_count += 1

    # --- PHASE 3: AUDIO ---
    # Saare audio inputs ko dhoondho
    audio_indices = []
    for idx, f_path in enumerate(input_files):
        # Hum check kar rahe hain ki kya ye input audio file hai
        # trackItemsMap se cross-check karna better hai
        pass 

    # Short version for Audio (Mixing all available audio inputs)
    audio_map = []
    for item_id in design.get("trackItemIds", []):
        item = track_items_map.get(item_id, {})
        if item.get("type") == "audio":
            abs_src = abs_media_path(item["details"]["src"])
            input_files.append(abs_src)
            audio_map.append(len(input_files) - 1)

    # Building the Final Command
    cmd = ["ffmpeg", "-y"]
    for f in input_files:
        cmd += ["-i", f]
    
    # Filter Complex string build
    filter_str = ";".join(filter_parts)
    
    # Audio Mixing logic
    if audio_map:
        amix_inputs = "".join([f"[{i}:a]" for i in audio_map])
        filter_str += f";{amix_inputs}amix=inputs={len(audio_map)}:duration=first[aout]"
    
    cmd += ["-filter_complex", filter_str]
    cmd += ["-map", last_label] # Final Video Label
    
    if audio_map:
        cmd += ["-map", "[aout]"]
    
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-t", str(duration), output_path]

    print("🚀 Executing FFmpeg...")
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