import subprocess
import os
import uuid

import json
from bson import ObjectId
from app.db.connection import db

FFMPEG = r"C:\ffmpeg-2025-12-28-git-9ab2a437a1-full_build\bin\ffmpeg.exe"

def render_preview(template: dict, output_path: str):
    """
    Minimal renderer:
    - Background video
    - Text overlay
    - Image overlay
    - Audio
    """

    design = template["template_json"]["design"]
    items = design["trackItemsMap"]

    base_cmd = [FFMPEG, "-y"]

    # ---------------- Base video ----------------
    bg_video = None
    for item in items.values():
        if item["type"] == "video":
            bg_video = item["details"]["src"]
            break

    if not bg_video:
        raise Exception("No background video found")

    base_cmd += ["-i", bg_video]

    filter_complex = []
    inputs_count = 1
    current_video = "[0:v]"

    # ---------------- Images ----------------
    for item in items.values():
        if item["type"] == "image":
            img = item["details"]["src"]
            base_cmd += ["-i", img]

            overlay = (
                f"{current_video}[{inputs_count}:v]"
                f"overlay=enable='between(t,{item['display']['from']/1000},"
                f"{item['display']['to']/1000})'"
            )
            filter_complex.append(overlay)
            current_video = f"[v{inputs_count}]"
            inputs_count += 1

    # ---------------- Text ----------------
    for item in items.values():
        if item["type"] == "text":
            text = item["details"]["text"].replace(":", "\\:")
            fontsize = item["details"].get("fontSize", 60)
            color = item["details"].get("color", "#ffffff")
            x = int(float(item["details"]["left"].replace("px", "")))
            y = int(float(item["details"]["top"].replace("px", "")))

            draw = (
                f"drawtext=text='{text}':"
                f"x={x}:y={y}:"
                f"fontsize={fontsize}:fontcolor={color}:"
                f"enable='between(t,{item['display']['from']/1000},"
                f"{item['display']['to']/1000})'"
            )
            filter_complex.append(draw)

    # ---------------- Audio ----------------
    for item in items.values():
        if item["type"] == "audio":
            base_cmd += ["-i", item["details"]["src"]]

    base_cmd += [
        "-filter_complex", ",".join(filter_complex),
        "-map", "0:v",
        "-map", "1:a?",
        "-t", "5",
        "-preset", "veryfast",
        output_path
    ]

    print("FFmpeg CMD:", base_cmd)
    subprocess.run(base_cmd, check=True)









# MEDIA_ROOT = "media/generated"

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

