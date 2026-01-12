import os
import json
import subprocess
from typing import Dict, Any

# ============================================================
# DEBUG HELPERS
# ============================================================

def debug(title: str):
    print(f"\n========== {title} ==========")


def ensure_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [value]


def to_local_path(url_or_path: str | None):
    debug("RESOLVING MEDIA PATH")

    if not url_or_path:
        print("❌ EMPTY SRC")
        return None

    print("RAW SRC:", url_or_path)

    media_root = os.path.abspath("media")

    # 1️⃣ If full URL
    if url_or_path.startswith("http"):
        if "/media/" in url_or_path:
            relative = url_or_path.split("/media/")[-1]
        else:
            relative = os.path.basename(url_or_path)
    else:
        relative = url_or_path

    print("RELATIVE PART:", relative)

    # 2️⃣ Try exact relative path
    candidate = os.path.abspath(os.path.join("media", relative))
    print("TRY PATH:", candidate)
    if os.path.exists(candidate):
        print("✅ FOUND")
        return candidate

    # 3️⃣ Try only filename (legacy support)
    filename = os.path.basename(relative)
    candidate = os.path.join(media_root, filename)
    print("TRY FLAT PATH:", candidate)
    if os.path.exists(candidate):
        print("✅ FOUND")
        return candidate

    print("❌ FILE NOT FOUND:", relative)
    return None


# ============================================================
# MAIN RENDER FUNCTION
# ============================================================

def render_preview(template: Dict[str, Any], output_path: str):
    debug("RENDER_PREVIEW START")

    print("FINAL OUTPUT PATH:", output_path)

    base_videos = ensure_list(template.get("base_video_url"))
    base_images = ensure_list(template.get("base_image_url"))
    base_audio = template.get("base_audio_url")

    template_json = template.get("template_json") or {}

    debug("BASE MEDIA FROM TEMPLATE")
    print("Base Videos:", base_videos)
    print("Base Images:", base_images)
    print("Base Audio:", base_audio)

    # ========================================================
    # PARSE TEMPLATE JSON
    # ========================================================

    design = template_json.get("design") or {}
    track_items = design.get("trackItemsMap") or {}

    video_inputs = []
    image_inputs = []
    audio_input = None

    v_idx = 0
    i_idx = 0

    debug("TRACK ITEMS SCAN")

    for item_id, item in track_items.items():
        item_type = item.get("type")
        details = item.get("details", {})
        src = details.get("src")

        print(f"\nTRACK ITEM {item_id}")
        print("TYPE:", item_type)
        print("SRC:", src)

        # ❗ IMPORTANT: override upload.* using base_* urls
        if item_type == "video":
            if v_idx < len(base_videos):
                print("OVERRIDE VIDEO SRC →", base_videos[v_idx])
                src = base_videos[v_idx]
                v_idx += 1

            local = to_local_path(src)
            if local:
                video_inputs.append(local)

        elif item_type == "image":
            if i_idx < len(base_images):
                print("OVERRIDE IMAGE SRC →", base_images[i_idx])
                src = base_images[i_idx]
                i_idx += 1

            local = to_local_path(src)
            if local:
                image_inputs.append(local)

        elif item_type == "audio":
            if base_audio:
                print("OVERRIDE AUDIO SRC →", base_audio)
                src = base_audio

            local = to_local_path(src)
            if local:
                audio_input = local

    debug("RESOLVED INPUT FILES")
    print("VIDEOS:", video_inputs)
    print("IMAGES:", image_inputs)
    print("AUDIO :", audio_input)

    # ========================================================
    # FFmpeg COMMAND BUILD
    # ========================================================

    if not video_inputs and not image_inputs:
        raise Exception("No valid media inputs found")

    cmd = ["ffmpeg", "-y"]

    for v in video_inputs:
        cmd += ["-i", v]

    for i in image_inputs:
        cmd += ["-loop", "1", "-i", i]

    if audio_input:
        cmd += ["-i", audio_input]

    filter_complex = []

    total_inputs = len(video_inputs) + len(image_inputs)
    for i in range(total_inputs):
        filter_complex.append(f"[{i}:v]scale=1080:1920,setsar=1[v{i}]")

    video_map = "".join([f"[v{i}]" for i in range(total_inputs)])
    filter_complex.append(f"{video_map}concat=n={total_inputs}:v=1:a=0[vout]")

    filter_str = ";".join(filter_complex)

    cmd += [
        "-filter_complex", filter_str,
        "-map", "[vout]"
    ]

    if audio_input:
        cmd += ["-map", f"{total_inputs}:a", "-shortest"]

    cmd += [
        "-r", "30",
        "-pix_fmt", "yuv420p",
        output_path
    ]

    debug("FFMPEG COMMAND")
    print(" ".join(cmd))

    # ========================================================
    # EXECUTE
    # ========================================================

    try:
        subprocess.run(cmd, check=True)
        print("✅ VIDEO RENDERED SUCCESSFULLY")

    except subprocess.CalledProcessError as e:
        print("❌ FFMPEG FAILED")
        raise Exception(str(e))





# import re
# from fastapi import APIRouter, Depends, HTTPException
# from fastapi.concurrency import run_in_threadpool
# from fastapi.responses import FileResponse
# from datetime import datetime
# from bson import ObjectId
# import json
# from app.db.connection import db
# from app.utils.auth import require_roles
# from app.services.video_renderer import render_preview

# import os 
# router = APIRouter(prefix="/templates", tags=["Templates"])


# # ================= CREATE TEMPLATE =================
# @router.post("/")
# async def create_template(
#     data: dict,
#     user=Depends(require_roles("company"))
# ):
#     print("User creating template:", user)

#     company = await db.companies.find_one({
#         "user_id": str(user["_id"])
#     })

#     print("Creating template for company:", company)

#     if not company:
#         raise HTTPException(400, "Company not found")

#     template_doc = {
#         "company_id": str(company["_id"]),
#         "template_name": data["template_name"],
#         "category": data.get("category", "general"),
#         "base_video_url": data.get("base_video_url"),
#         "base_image_url": data.get("base_image_url"),
#         "base_audio_url": data.get("base_audio_url"),
#         "duration": data.get("duration"),
#         "trim": data.get("trim"),
#         "template_json": data["template_json"],
#         "type": data.get("type", "video"),
#         "status": "active",
#         "created_at": datetime.utcnow(),
#         "updated_at": datetime.utcnow(),
#     }

#     result = await db.templates.insert_one(template_doc)

#     return {
#         "message": "Template created successfully",
#         "template_id": str(result.inserted_id)
#     }


# # ================= LIST TEMPLATES =================
# @router.get("/")
# async def list_templates(user=Depends(require_roles("company"))):

#     company = await db.companies.find_one({
#         "user_id": str(user["_id"])
#     })

#     templates = await db.templates.find({
#         "company_id": str(company["_id"]),
#         "status": "active"
#     }).to_list(length=1000)

#     for t in templates:
#         t["id"] = str(t["_id"])
#         del t["_id"]

#     return {"templates": templates}


# # ================= GET TEMPLATE =================
# @router.get("/{template_id}")
# async def get_template(template_id: str):

#     template = await db.templates.find_one({
#         "_id": ObjectId(template_id),
#         "status": "active"
#     })

#     if not template:
#         raise HTTPException(404, "Template not found")

#     template["id"] = str(template["_id"])
#     del template["_id"]

#     return {"template": template}


# # ================= UPDATE TEMPLATE (PATCH) =================
# @router.patch("/{template_id}")
# async def update_template(
#     template_id: str,
#     data: dict,
#     user=Depends(require_roles("company"))
# ):
#     await db.templates.update_one(
#         {"_id": ObjectId(template_id)},
#         {"$set": {**data, "updated_at": datetime.utcnow()}}
#     )

#     return {"message": "Template updated successfully"}


# # ================= DELETE TEMPLATE =================
# @router.delete("/{template_id}")
# async def delete_template(template_id: str):

#     await db.templates.update_one(
#         {"_id": ObjectId(template_id)},
#         {"$set": {"status": "deleted"}}
#     )

#     return {"message": "Template deleted"}


# # ================= PREVIEW TEMPLATE =================
# @router.post("/{template_id}/preview")
# async def preview_template(template_id: str):
#     template = await db.templates.find_one({"_id": ObjectId(template_id)})
#     if not template:
#         raise HTTPException(status_code=404, detail="Template Does not exist!")

#     # Fetch company name for watermarking
#     company_id = template.get("company_id")
#     company_name = "Our Company" # Default fallback
    
#     if company_id:
#         company_data = await db.companies.find_one({"_id": ObjectId(company_id)})
#         if company_data:
#             company_name = company_data.get("company_name") or company_data.get("name") or "Our Company"

#     # 2. Prepare output path
#     media_dir = os.path.abspath("media")
#     os.makedirs(media_dir, exist_ok=True)
#     preview_filename = f"{template_id}_preview.mp4"
#     print("Preview Of Filename is",preview_filename)
#     preview_path = os.path.join(media_dir, preview_filename)
#     print("Preview path is is",preview_filename)

#     try:
#         # 3. Render preview in thread pool
#         await run_in_threadpool(render_preview, template, preview_path)
        
#         # return {"status": "success", "preview_url": f"/media/{preview_filename}"}
#         return FileResponse(
#             path=preview_path, 
#             media_type="video/mp4", 
#             filename=preview_filename
#         )
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^}]+)\s*}}")
# def get_nested_value(data: dict, path: str):
#     """
#     Supports dot notation like:
#     user.email
#     company.company_name
#     """
#     try:
#         for key in path.split("."):
#             data = data.get(key)
#             if data is None:
#                 return ""
#         return str(data)
#     except Exception:
#         return ""

# # def replace_placeholders(template_json: dict, customer: dict) -> dict:
# #     """
# #     Replaces {{field}} and {{nested.field}} placeholders
# #     using customer JSON
# #     """
# #     template_str = json.dumps(template_json)

# #     def replacer(match):
# #         key_path = match.group(1)  # e.g. user.email
# #         return get_nested_value(customer, key_path)

# #     template_str = PLACEHOLDER_PATTERN.sub(replacer, template_str)

# #     return json.loads(template_str)

# def replace_placeholders(template_json: dict, customer: dict) -> dict:
#     template_str = json.dumps(template_json)

#     replacements = {
#         "{{customer_company_name}}": customer.get("customer_company_name", ""),
#         "{{full_name}}": customer.get("full_name", ""),
#         "{{city}}": customer.get("city", ""),
#         "{{phone_number}}": customer.get("phone_number", "")
#     }

#     for key, value in replacements.items():
#         template_str = template_str.replace(key, value)

#     return json.loads(template_str)
    
# @router.post("/{template_id}/preview/{customer_id}")
# async def preview_template_customer(template_id: str, customer_id: str):

#     template = await db.templates.find_one({"_id": ObjectId(template_id)})
#     if not template:
#         raise HTTPException(status_code=404, detail="Template does not exist")

#     customer = await db.customers.find_one({"_id": ObjectId(customer_id)})
#     print("Customer data:", customer)
#     if not customer:
#         raise HTTPException(status_code=404, detail="Customer does not exist")

#     # 🔹 PLACEHOLDER REPLACEMENT
#     template["template_json"] = replace_placeholders(
#         template["template_json"],
#         customer
#     )

#     media_dir = os.path.abspath("media")
#     os.makedirs(media_dir, exist_ok=True)

#     preview_filename = f"{template_id}_{customer_id}_preview.mp4"
#     preview_path = os.path.join(media_dir, preview_filename)

#     try:
#         await run_in_threadpool(render_preview, template, preview_path)

#         return FileResponse(
#             path=preview_path,
#             media_type="video/mp4",
#             filename=preview_filename
#         )

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @router.get("/{template_id}/download/{customer_id}")
# async def download_video(template_id: str, customer_id: str):

#     filename = f"{template_id}_{customer_id}_preview.mp4"
#     file_path = os.path.abspath(os.path.join("media", filename))

#     if not os.path.exists(file_path):
#         raise HTTPException(
#             status_code=404,
#             detail="Video file does not exist. You must first generate a preview."
#         )

#     return FileResponse(
#         path=file_path,
#         media_type="video/mp4",
#         filename=filename
#     )