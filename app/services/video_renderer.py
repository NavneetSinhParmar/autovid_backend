import subprocess
import os
import uuid

import json
from bson import ObjectId
from app.db.connection import db

MEDIA_ROOT = "media/generated"

def render_video(task_id: str):
    task = db.video_tasks.find_one({"_id": ObjectId(task_id)})
    template = db.templates.find_one({"_id": ObjectId(task["template_id"])})
    customer = db.customers.find_one({"_id": ObjectId(task["customer_id"])})

    template_json = template["template_json"]
    base_video = template["base_video_url"]

    os.makedirs(MEDIA_ROOT, exist_ok=True)
    output_path = f"{MEDIA_ROOT}/{task_id}.mp4"

    # 👉 SIMPLE TEXT OVERLAY (extend later)
    text_layer = template_json["layers"][0]
    text = text_layer["text"].replace(
        "{{full_name}}", customer["full_name"]
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i", base_video,
        "-vf", f"drawtext=text='{text}':x=200:y=300:fontsize=40:fontcolor=white",
        output_path
    ]

    subprocess.run(cmd, check=True)

    return output_path

def ensure_list(val):
    if not val:
        return []
    if isinstance(val, list):
        return val
    return [val]

FFMPEG = r"C:\ffmpeg-2025-12-28-git-9ab2a437a1-full_build\bin\ffmpeg.exe"
FONT = "C\\:/Windows/Fonts/arial.ttf" 

def to_local_path(url_or_path):
    if not url_or_path:
        return None
    # 1. Extract filename from URL or path
    filename = url_or_path.split("/")[-1]

    # 2. Construct absolute path in media directory
    base_dir = os.path.abspath("media")
    abs_path = os.path.join(base_dir, filename)

    print(f"DEBUG: Looking for file at -> {abs_path}")

    if os.path.exists(abs_path):
        return abs_path
    # 3. Check if it's a full URL containing /media/
    if "/media/" in url_or_path:
        relative_part = url_or_path.split("/media/")[-1]
        abs_path = os.path.abspath(os.path.join("media", relative_part))
        print(f"DEBUG: Checking file at -> {abs_path}")
        if os.path.exists(abs_path):
            return abs_path

    print(f"❌ FILE NOT FOUND: {filename} is missing in {base_dir}")
    return None


def render_preview(template: dict, output_path: str):
    print("DEBUG: Processing Template...")

    # --- 1. Input Files ---
    raw_videos = template.get("base_video_url") or []
    if isinstance(raw_videos, str): raw_videos = [raw_videos]
    
    raw_images = template.get("base_image_url") or []
    if isinstance(raw_images, str): raw_images = [raw_images]
    
    raw_audio = template.get("base_audio_url") or []
    if isinstance(raw_audio, str): raw_audio = [raw_audio]

    cmd = [FFMPEG, "-y"]
    
    # Video Inputs mapping
    video_count = 0
    for v in raw_videos:
        path = to_local_path(v)
        if path and os.path.exists(path):
            cmd += ["-i", path.replace("\\", "/")]
            video_count += 1

    if video_count == 0:
        raise Exception("Error: Koi bhi valid video file nahi mili. Base video missing hai.")

    # Image Inputs mapping
    image_count = 0
    for img in raw_images:
        path = to_local_path(img)
        if path and os.path.exists(path):
            cmd += ["-i", path.replace("\\", "/")]
            image_count += 1

    # Audio Input mapping
    has_audio = False
    if raw_audio and len(raw_audio) > 0:
        a_path = to_local_path(raw_audio[0])
        if a_path and os.path.exists(a_path):
            cmd += ["-i", a_path.replace("\\", "/")]
            has_audio = True

    # --- 2. Filter Complex Chain ---
    
    v_prep = ""
    v_nodes = ""
    for i in range(video_count):
        v_prep += f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];"
        v_nodes += f"[v{i}]"
    
    filter_str = f"{v_prep}{v_nodes}concat=n={video_count}:v=1:a=0[basevid];"
    last_node = "[basevid]"


    for j in range(image_count):
        img_idx = video_count + j
        out_node = f"[img_over{j}]"
        filter_str += f"[{img_idx}:v]scale=500:-1[img_s{j}];"
        filter_str += f"{last_node}[img_s{j}]overlay=(W-w)/2:(H-h)/2{out_node};"
        last_node = out_node

    # Text Overlays from template JSON
    template_json = template.get("template_json") or {}
    design = template_json.get("design") or {}
    items = design.get("trackItemsMap") or {}

    txt_count = 0
    for item in items.values():
        if item and item.get("type") == "text":
            details = item.get("details") or {}
            raw_text = details.get("text") or ""
            
            clean_text = raw_text.replace(":", "\\:").replace("'", "").replace("%", "%%")
            
            x = str(details.get("left", "0")).replace("px", "")
            y = str(details.get("top", "0")).replace("px", "")
            fs = details.get("fontSize", 40)
            color = details.get("color", "white")
            
            out_node = f"[txt{txt_count}]"
            filter_str += f"{last_node}drawtext=fontfile='{FONT}':text='{clean_text}':x={x}:y={y}:fontsize={fs}:fontcolor={color}{out_node};"
            last_node = out_node
            txt_count += 1

    # --- 3. Execution ---
    cmd += ["-filter_complex", filter_str.rstrip(';')]
    cmd += ["-map", last_node]

    if has_audio:       
        audio_idx = video_count + image_count
        cmd += ["-map", f"{audio_idx}:a"]
    else:
        # Fallback to first video's audio if exists
        cmd += ["-map", "0:a?"]

    cmd += [
        "-c:v", "libx264", "-preset", "ultrafast", 
        "-pix_fmt", "yuv420p", "-t", "15", output_path.replace("\\", "/")
    ]

    print("DEBUG: Executing FFmpeg command...")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    
    if result.returncode != 0:
        print("FFMPEG ERROR:", result.stderr)
        raise Exception(f"FFmpeg render failed with code {result.returncode}")

    return output_path