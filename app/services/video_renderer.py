import subprocess
import os
import uuid
import re

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
    print("DEBUG: Processing Template with Dynamic JSON...")

    # Extract template JSON and design settings
    template_json = template.get("template_json") or {}
    design = template_json.get("design") or {}
    track_items_map = design.get("trackItemsMap") or {}
    
    # Get video resolution and FPS from template JSON
    size = design.get("size", {})
    video_width = size.get("width", 1920)
    video_height = size.get("height", 1080)
    fps = design.get("fps", 30)
    
    # Get duration from template (convert milliseconds to seconds)
    duration_ms = template.get("duration") or template.get("trim", {}).get("end", 15993.426638194968)
    duration_seconds = duration_ms / 1000.0 if duration_ms > 100 else duration_ms
    
    print(f"Video Settings: {video_width}x{video_height} @ {fps}fps, Duration: {duration_seconds}s")

    # Build input file mapping
    cmd = [FFMPEG, "-y"]
    input_map = {}  # Maps item_id -> input_index
    input_index = 0
    
    # Process all items to collect unique media files
    media_files = {}  # Maps src -> input_index
    
    for item_id, item in track_items_map.items():
        item_type = item.get("type")
        if item_type in ["video", "image", "audio"]:
            details = item.get("details", {})
            src = details.get("src")
            print(f"Processing item {item_id} of type {item_type} with src: {src}")
            if src:
                if src not in media_files:
                    media_files[src] = input_index
                    input_map[item_id] = input_index
                    input_index += 1
                else:
                    input_map[item_id] = media_files[src]

    # Add all media files as inputs (in order)
    sorted_media = sorted(media_files.items(), key=lambda x: x[1])
    actual_input_map = {}  # Maps original input_index -> actual input_index
    
    for src, orig_idx in sorted_media:
        path = to_local_path(src)
        if path and os.path.exists(path):
            actual_idx = len([x for x in actual_input_map.values() if x is not None])
            actual_input_map[orig_idx] = actual_idx
            cmd += ["-i", path.replace("\\", "/")]
            print(f"Added input [{actual_idx}]: {path}")
        else:
            actual_input_map[orig_idx] = None
            print(f"WARNING: File not found: {src}")
    
    # Update input_map with actual indices
    for item_id in list(input_map.keys()):
        orig_idx = input_map[item_id]
        if orig_idx in actual_input_map and actual_input_map[orig_idx] is not None:
            input_map[item_id] = actual_input_map[orig_idx]
        else:
            del input_map[item_id]  # Remove items with missing files

    # Helper to convert milliseconds to seconds
    def ms_to_sec(ms):
        return ms / 1000.0 if ms > 100 else ms

    # Helper to parse position values
    def parse_position(value, default=0):
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            return float(value.replace("px", "").replace("px", ""))
        return default

    # Find base video (video that starts at 0 and covers significant duration)
    base_video_item = None
    base_video_idx = None
    base_video_id = None
    
    for item_id, item in track_items_map.items():
        if item.get("type") == "video":
            display = item.get("display", {})
            start_time = ms_to_sec(display.get("from", 0))
            end_time = ms_to_sec(display.get("to", duration_seconds * 1000))
            if start_time == 0 and end_time >= duration_seconds * 0.8 and item_id in input_map:
                base_video_item = item
                base_video_idx = input_map[item_id]
                base_video_id = item_id
                break
    
    # Create base canvas
    filter_parts = []
    node_counter = 0
    
    if base_video_item:
        print("Using base video for background.",base_video_item)
        # Use first video as base
        display = base_video_item.get("display", {})
        trim_info = base_video_item.get("trim", {})
        details = base_video_item.get("details", {})
        
        trim_start = ms_to_sec(trim_info.get("from", 0))
        trim_end = ms_to_sec(trim_info.get("to", duration_seconds * 1000))
        base_display_end = ms_to_sec(display.get("to", duration_seconds * 1000))
        
        # Get base video duration
        base_video_duration = min(trim_end - trim_start, base_display_end)
        
        # Scale and trim base video, then loop to fill full duration
        filter_parts.append(
            f"[{base_video_idx}:v]trim=start={trim_start}:end={trim_start + base_video_duration},"
            f"setpts=PTS-STARTPTS,"
            f"scale={video_width}:{video_height}:force_original_aspect_ratio=decrease,"
            f"pad={video_width}:{video_height}:(ow-iw)/2:(oh-ih)/2,"
            f"loop=loop=-1:size=1:start=0,"
            f"trim=duration={duration_seconds}[base]"
        )
        current_node = "[base]"
    else:
        # Create black canvas
        filter_parts.append(f"color=c=black:s={video_width}x{video_height}:d={duration_seconds}[base]")
        current_node = "[base]"

    # Process video items (skip base video if used)
    # Process video items (skip base video if used)
    video_overlay_count = 0
    for item_id, item in track_items_map.items():
        if item.get("type") == "video" and item_id != base_video_id:
            display = item.get("display", {})
            trim_info = item.get("trim", {})
            details = item.get("details", {})
            
            start_time = ms_to_sec(display.get("from", 0))
            end_time = ms_to_sec(display.get("to", duration_seconds * 1000))
            trim_start = ms_to_sec(trim_info.get("from", 0))
            trim_end = ms_to_sec(trim_info.get("to", end_time * 1000))
            
            if item_id in input_map:
                input_idx = input_map[item_id]
                src = details.get("src")
                
                # Get position and transform
                left = parse_position(details.get("left", 0))
                top = parse_position(details.get("top", 0))
                width = details.get("width", video_width)
                height = details.get("height", video_height)
                opacity = details.get("opacity", 100) / 100.0
                transform = details.get("transform", "scale(1, 1)")
                
                # Parse scale from transform
                scale_x = 1.0
                scale_y = 1.0
                if "scale" in transform:
                    scale_match = re.search(r'scale\(([^,]+),([^)]+)\)', transform)
                    if scale_match:
                        scale_x = float(scale_match.group(1))
                        scale_y = float(scale_match.group(2))
                
                # Calculate scaled dimensions
                scaled_width = int(width * scale_x)
                scaled_height = int(height * scale_y)
                
                # Ensure minimum dimensions
                scaled_width = max(scaled_width, 1)
                scaled_height = max(scaled_height, 1)
                
                # Calculate actual video duration needed
                video_duration = min(trim_end - trim_start, end_time - start_time)
                
                # Trim and scale video WITHOUT loop filter
                video_node = f"[v{node_counter}]"
                # Scale to fit, crop to ensure we're within bounds, then pad
                scale_temp = f"[vtemp{node_counter}]"
                crop_temp = f"[vcrop{node_counter}]"
                filter_parts.append(
                    f"[{input_idx}:v]trim=start={trim_start}:end={trim_start + video_duration},"
                    f"setpts=PTS-STARTPTS,"
                    f"scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=decrease{scale_temp}"
                )
                # Crop to ensure dimensions are <= target (safety measure)
                filter_parts.append(
                    f"{scale_temp}crop='min(iw,{scaled_width})':'min(ih,{scaled_height})'{crop_temp}"
                )
                # Pad and set timing WITHOUT loop
                filter_parts.append(
                    f"{crop_temp}pad={scaled_width}:{scaled_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"setpts=PTS+{start_time}/TB,"
                    f"trim=duration={end_time - start_time}{video_node}"
                )
                
                # Overlay video at specific time with opacity
                overlay_node = f"[overlay_v{video_overlay_count}]"
                # Handle negative positions - clamp to 0 minimum for overlay
                overlay_x = max(0, int(left))
                overlay_y = max(0, int(top))
                
                # Apply opacity if needed
                if opacity < 1.0:
                    vid_opacity_node = f"[vidopacity{node_counter}]"
                    filter_parts.append(
                        f"{video_node}format=yuva420p,colorchannelmixer=aa={opacity}{vid_opacity_node}"
                    )
                    video_node = vid_opacity_node
                
                # Use overlay with enable expression for timing
                filter_parts.append(
                    f"{current_node}{video_node}overlay={overlay_x}:{overlay_y}:enable='between(t,{start_time},{end_time})'{overlay_node}"
                )
                
                current_node = overlay_node
                node_counter += 1
                video_overlay_count += 1

    # Process image items
    image_overlay_count = 0
    for item_id, item in track_items_map.items():
        if item.get("type") == "image":
            display = item.get("display", {})
            details = item.get("details", {})
            
            start_time = ms_to_sec(display.get("from", 0))
            end_time = ms_to_sec(display.get("to", duration_seconds * 1000))
            
            if item_id in input_map:
                input_idx = input_map[item_id]
                
                # Get position and transform
                left = parse_position(details.get("left", 0))
                top = parse_position(details.get("top", 0))
                width = details.get("width", 500)
                height = details.get("height", 500)
                opacity = details.get("opacity", 100) / 100.0
                transform = details.get("transform", "scale(1, 1)")
                
                # Parse scale from transform
                scale_x = 1.0
                scale_y = 1.0
                if "scale" in transform:
                    scale_match = re.search(r'scale\(([^,]+),([^)]+)\)', transform)
                    if scale_match:
                        scale_x = float(scale_match.group(1))
                        scale_y = float(scale_match.group(2))
                
                # Calculate scaled dimensions
                scaled_width = int(width * scale_x)
                scaled_height = int(height * scale_y)
                
                # Ensure minimum dimensions
                scaled_width = max(scaled_width, 1)
                scaled_height = max(scaled_height, 1)
                
                # Scale image and set duration
                img_node = f"[img{node_counter}]"
                # Scale to fit, crop to ensure we're within bounds, then pad
                img_temp = f"[imgtemp{node_counter}]"
                img_crop = f"[imgcrop{node_counter}]"
                filter_parts.append(
                    f"[{input_idx}:v]scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=decrease{img_temp}"
                )
                # Crop to ensure dimensions are <= target (safety measure)
                filter_parts.append(
                    f"{img_temp}crop='min(iw,{scaled_width})':'min(ih,{scaled_height})'{img_crop}"
                )
                # Now pad is safe since dimensions are guaranteed <= target
                filter_parts.append(
                    f"{img_crop}pad={scaled_width}:{scaled_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"setpts=PTS+{start_time}/TB,"
                    f"loop=loop=-1:size=1:start=0,"
                    f"trim=duration={end_time - start_time}{img_node}"
                )
                
                # Overlay image at specific time with opacity
                overlay_node = f"[overlay_img{image_overlay_count}]"
                # Handle negative positions - clamp to 0 minimum for overlay
                overlay_x = max(0, int(left))
                overlay_y = max(0, int(top))
                
                # Apply opacity if needed
                if opacity < 1.0:
                    img_opacity_node = f"[imgopacity{node_counter}]"
                    filter_parts.append(
                        f"{img_node}format=yuva420p,colorchannelmixer=aa={opacity}{img_opacity_node}"
                    )
                    img_node = img_opacity_node
                
                # Use overlay with enable expression for timing
                filter_parts.append(
                    f"{current_node}{img_node}overlay={overlay_x}:{overlay_y}:enable='between(t,{start_time},{end_time})'{overlay_node}"
                )
                
                current_node = overlay_node
                node_counter += 1
                image_overlay_count += 1

    # Process text items
    text_count = 0
    for item_id, item in track_items_map.items():
        if item.get("type") == "text":
            display = item.get("display", {})
            details = item.get("details", {})
            
            start_time = ms_to_sec(display.get("from", 0))
            end_time = ms_to_sec(display.get("to", duration_seconds * 1000))
            
            raw_text = details.get("text", "")
            def ffmpeg_escape_text(text: str) -> str:
                if not text:
                    return ""
                return (
                    text.replace("\\", "\\\\")
                        .replace(":", "\\:")
                        .replace("'", "\\'")
                        .replace(",", "\\,")
                        .replace(";", "\\;")
                        .replace("=", "\\=")
                        .replace("\n", "\\n")
                        .replace("\r", "")
                        .replace("%", "\\%")
                        .replace("[", "\\[")
                        .replace("]", "\\]")
                )
            clean_text = ffmpeg_escape_text(raw_text)


            # Clean text for FFmpeg
            # clean_text = raw_text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "%%").replace("[", "\\[").replace("]", "\\]")
            
            x = parse_position(details.get("left", 0))
            y = parse_position(details.get("top", 0))
            font_size = details.get("fontSize", 40)
            color = details.get("color", "white")
            font_family = details.get("fontFamily", "Arial")
            opacity = details.get("opacity", 100) / 100.0
            
            # Get boxShadow properties
            box_shadow = details.get("boxShadow", {})
            shadow_x = box_shadow.get("x", 0) if isinstance(box_shadow, dict) else 0
            shadow_y = box_shadow.get("y", 0) if isinstance(box_shadow, dict) else 0
            shadow_color = box_shadow.get("color", "#000000") if isinstance(box_shadow, dict) else "#000000"
            shadow_blur = box_shadow.get("blur", 0) if isinstance(box_shadow, dict) else 0
            
            # Get textShadow
            text_shadow = details.get("textShadow", "none")
            if text_shadow != "none" and isinstance(text_shadow, str):
                # Parse text shadow if it's a string like "2px 2px 4px #000000"
                pass  # FFmpeg drawtext doesn't support text shadow directly, we'll use boxShadow
            
            # Get border properties
            border_width = details.get("borderWidth", 0)
            border_color = details.get("borderColor", "transparent")
            if border_color == "transparent":
                border_color = color
            
            # Get background color
            bg_color = details.get("backgroundColor", "transparent")
            
            # Get text stroke (WebkitTextStroke)
            stroke_color = details.get("WebkitTextStrokeColor", "transparent")
            stroke_width = parse_position(details.get("WebkitTextStrokeWidth", "0px"))
            
            # Build drawtext filter with all properties
            text_node = f"[txt{text_count}]"
            
            # Convert hex color to RGB if needed
            def hex_to_rgb(hex_color):
                hex_color = hex_color.lstrip('#')
                if len(hex_color) == 6:
                    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                return (255, 255, 255)
            
            # Parse color
            text_color_rgb = hex_to_rgb(color) if color.startswith('#') else (255, 255, 255)
            text_color_str = f"0x{text_color_rgb[0]:02x}{text_color_rgb[1]:02x}{text_color_rgb[2]:02x}"
            
            drawtext_params = [
                f"fontfile='{FONT}'",
                f"text='{clean_text}'",
                f"x={x}",
                f"y={y}",
                f"fontsize={font_size}",
                f"fontcolor={text_color_str}",
            ]
            
            # Add alpha/opacity
            if opacity < 1.0:
                alpha_hex = int(opacity * 255)
                fontcolor = f"{text_color_str}{alpha_hex:02x}"
                drawtext_params.append(f"fontcolor={fontcolor}")

            
            # Add border if specified
            if border_width > 0 and border_color != "transparent":
                border_rgb = hex_to_rgb(border_color) if border_color.startswith('#') else (0, 0, 0)
                border_color_str = f"0x{border_rgb[0]:02x}{border_rgb[1]:02x}{border_rgb[2]:02x}"
                drawtext_params.append(f"borderw={border_width}")
                drawtext_params.append(f"bordercolor={border_color_str}")
            
            # Add text stroke if specified
            if stroke_width > 0 and stroke_color != "transparent":
                stroke_rgb = hex_to_rgb(stroke_color) if stroke_color.startswith('#') else (255, 255, 255)
                stroke_color_str = f"0x{stroke_rgb[0]:02x}{stroke_rgb[1]:02x}{stroke_rgb[2]:02x}"
                drawtext_params.append(f"line_spacing={stroke_width}")
                # Note: FFmpeg drawtext doesn't have direct stroke, but we can use border as stroke
            
            # Add box shadow (simulated with shadow layer)
            if shadow_x != 0 or shadow_y != 0:
                # Create shadow layer first (behind text)
                shadow_node = f"[txtshadow{text_count}]"
                shadow_rgb = hex_to_rgb(shadow_color) if shadow_color.startswith('#') else (0, 0, 0)
                shadow_color_str = f"0x{shadow_rgb[0]:02x}{shadow_rgb[1]:02x}{shadow_rgb[2]:02x}"
                
                shadow_params = [
                    f"fontfile='{FONT}'",
                    f"text='{clean_text}'",
                    f"x={x + shadow_x}",
                    f"y={y + shadow_y}",
                    f"fontsize={font_size}",
                    f"fontcolor={shadow_color_str}",
                    f"alpha=0.5",
                ]
                if border_width > 0:
                    shadow_params.append(f"borderw={border_width}")
                    shadow_params.append(f"bordercolor={shadow_color_str}")
                
                filter_parts.append(
                    f"{current_node}drawtext={':'.join(shadow_params)}"
                    f":enable='between(t,{start_time},{end_time})'"
                    f"{shadow_node}"
                )

                # Then overlay text on shadow
                filter_parts.append(
                    f"{shadow_node}drawtext={':'.join(drawtext_params)}"
                    f":enable='between(t,{start_time},{end_time})'"
                    f"{text_node}"
                )

            else:
                filter_parts.append(
                f"{current_node}drawtext={':'.join(drawtext_params)}"
                f":enable='between(t,{start_time},{end_time})'"
                f"{text_node}"
            )

            
            current_node = text_node
            text_count += 1

    # Process audio items and mix them
    audio_inputs = []
    audio_count = 0
    for item_id, item in track_items_map.items():
        if item.get("type") == "audio":
            display = item.get("display", {})
            trim_info = item.get("trim", {})
            details = item.get("details", {})
            
            start_time = ms_to_sec(display.get("from", 0))
            end_time = ms_to_sec(display.get("to", duration_seconds * 1000))
            trim_start = ms_to_sec(trim_info.get("from", 0))
            trim_end = ms_to_sec(trim_info.get("to", end_time * 1000))
            volume = details.get("volume", 100) / 100.0
            
            if item_id in input_map:
                input_idx = input_map[item_id]
                audio_node = f"[a{audio_count}]"
                # Calculate actual duration needed
                actual_duration = min(trim_end - trim_start, end_time - start_time)
                
                # Trim audio first
                trim_node = f"[atrim{audio_count}]"
                filter_parts.append(
                    f"[{input_idx}:a]atrim=start={trim_start}:end={trim_start + actual_duration},"
                    f"asetpts=PTS-STARTPTS{trim_node}"
                )
                
                # Apply volume
                vol_node = f"[avol{audio_count}]"
                filter_parts.append(
                    f"{trim_node}volume={volume}{vol_node}"
                )
                
                # Add delay and pad to full duration
                filter_parts.append(
                    f"{vol_node}adelay={int(start_time * 1000)}|{int(start_time * 1000)},"
                    f"apad=pad_dur={duration_seconds}{audio_node}"
                )
                
                audio_inputs.append(audio_node)
                audio_count += 1

    # Mix all audio tracks
    if audio_inputs:
        if len(audio_inputs) == 1:
            final_audio = audio_inputs[0]
        else:
            mix_parts = "".join(audio_inputs)
            final_audio = "[final_audio]"
            filter_parts.append(f"{mix_parts}amix=inputs={len(audio_inputs)}:duration=longest{final_audio}")
    else:
        # Create silent audio track
        final_audio = "[silent_audio]"
        filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{duration_seconds}{final_audio}")

    # Build final filter complex
    filter_complex = ";".join(filter_parts)
    
    # Build command
    cmd += ["-filter_complex", filter_complex]


    cmd += ["-map", current_node]
    cmd += ["-map", final_audio]
    
    cmd += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", str(duration_seconds),
        output_path.replace("\\", "/")
    ]

    print("DEBUG: Executing FFmpeg command...")
    print(f"Filter complex length: {len(filter_complex)} chars")
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    
    if result.returncode != 0:
        print("FFMPEG ERROR:", result.stderr)
        print("FFMPEG STDOUT:", result.stdout)
        raise Exception(f"FFmpeg render failed with code {result.returncode}: {result.stderr[:500]}")

    print("DEBUG: Video rendered successfully!")
    return output_path