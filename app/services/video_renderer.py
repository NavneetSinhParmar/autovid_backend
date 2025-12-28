import subprocess
import os
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

