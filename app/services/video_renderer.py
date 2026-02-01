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
FFMPEG = "ffmpeg"

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
FONT_PATH = os.path.join(BASE_DIR, "Fonts", "arial.ttf")
FONT_PATH = FONT_PATH.replace("\\", "/")
PX_RE = re.compile(r"-?\d+(\.\d+)?")
FONT_CACHE_DIR = os.path.join(MEDIA_ROOT, "font_cache")

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

# Function to compute absolute media path
# Converts relative paths to absolute paths based on MEDIA_ROOT
# Raises ValueError for remote URLs
# Logs input and resolved paths for debugging
def abs_media_path(path: str) -> str:
    path = path.replace("\\", "/")

    if path.startswith("http"):
        raise ValueError("Remote URLs not supported")

    path = path.replace("./media/", "")
    path = path.replace("media/", "")
    path = path.lstrip("/")
    media_root = MEDIA_ROOT.replace("\\", "/")
    full_path = os.path.join(media_root, path)
    full_path = full_path.replace("\\", "/")
    
    return full_path

# Function to ensure a file exists at the given path
# Raises FileNotFoundError if the file does not exist
def ensure_file_exists(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Media file not found: {path}")

# Function to parse position values
# Handles strings with 'px' suffix and converts to float
# Returns 0.0 for invalid values
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

# Function to escape text for FFmpeg compatibility
# Escapes special characters like ':', '\', and '%'
def ffmpeg_escape_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace(":", "\\:")
            .replace("'", "\\'")
            .replace("%", "\\%")
            .replace("[", "\\[")
            .replace("]", "\\]")
    )

def parse_color(value, default=(255, 255, 255, 1.0)):
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return default
        if v.lower() == "transparent":
            return (0, 0, 0, 0.0)
        if v.startswith("#"):
            hex_color = v[1:]
            if len(hex_color) == 3:
                r = int(hex_color[0] * 2, 16)
                g = int(hex_color[1] * 2, 16)
                b = int(hex_color[2] * 2, 16)
                return (r, g, b, 1.0)
            if len(hex_color) == 4:
                r = int(hex_color[0] * 2, 16)
                g = int(hex_color[1] * 2, 16)
                b = int(hex_color[2] * 2, 16)
                a = int(hex_color[3] * 2, 16) / 255.0
                return (r, g, b, a)
            if len(hex_color) in (6, 8):
                r = int(hex_color[0:2], 16)
                g = int(hex_color[2:4], 16)
                b = int(hex_color[4:6], 16)
                a = 1.0
                if len(hex_color) == 8:
                    a = int(hex_color[6:8], 16) / 255.0
                return (r, g, b, a)
        if v.lower().startswith("rgba(") and v.endswith(")"):
            parts = [p.strip() for p in v[5:-1].split(",")]
            if len(parts) == 4:
                r, g, b = [int(float(x)) for x in parts[:3]]
                a = float(parts[3])
                return (r, g, b, max(0.0, min(1.0, a)))
        if v.lower().startswith("rgb(") and v.endswith(")"):
            parts = [p.strip() for p in v[4:-1].split(",")]
            if len(parts) == 3:
                r, g, b = [int(float(x)) for x in parts]
                return (r, g, b, 1.0)
    return default

def ffmpeg_color(color_tuple, extra_alpha=1.0):
    r, g, b, a = color_tuple
    alpha = max(0.0, min(1.0, a * extra_alpha))
    return f"0x{r:02x}{g:02x}{b:02x}@{alpha:.3f}"

def resolve_canvas_size(design, default_w=1920, default_h=1080):
    size = design.get("size", {}) if isinstance(design, dict) else {}
    try:
        width = int(size.get("width", default_w))
    except Exception:
        width = default_w
    try:
        height = int(size.get("height", default_h))
    except Exception:
        height = default_h
    return max(1, width), max(1, height)

def resolve_fps(design, default=30):
    try:
        return int(design.get("fps", default))
    except Exception:
        return default

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

def download_font(font_url: str) -> str:
    if not font_url:
        return ""
    ensure_dir(FONT_CACHE_DIR)
    url_hash = hashlib.sha256(font_url.encode("utf-8")).hexdigest()[:16]
    ext = os.path.splitext(urllib.parse.urlparse(font_url).path)[1] or ".ttf"
    font_path = os.path.join(FONT_CACHE_DIR, f"{url_hash}{ext}")
    if os.path.exists(font_path):
        return font_path
    resp = requests.get(font_url, timeout=20)
    resp.raise_for_status()
    with open(font_path, "wb") as f:
        f.write(resp.content)
    return font_path

# Resolve font file paths
# Download fonts from URLs or map common font names to local files
# Fallback to Arial if no match is found
def resolve_font_file(details: Dict[str, Any]) -> str:
    font_url = details.get("fontUrl") or details.get("fontURL")
    if font_url:
        try:
            font_path = download_font(font_url)
            if os.path.exists(font_path):
                return font_path.replace("\\", "/")
        except Exception:
            pass
    
    font_family = details.get("fontFamily", "arial")
    
    # Convert to lowercase for comparison
    font_family_lower = str(font_family).lower()
    
    # Common font mappings
    font_mappings = {
        "arial": "arial.ttf",
        "helvetica": "arial.ttf",  # Helvetica often mapped to Arial
        "times new roman": "times.ttf",
        "times": "times.ttf",
        "courier new": "cour.ttf",
        "verdana": "verdana.ttf",
        "tahoma": "tahoma.ttf",
        "georgia": "georgia.ttf",
    }
    
    # Check mapped fonts
    if font_family_lower in font_mappings:
        font_file = font_mappings[font_family_lower]
        font_path = os.path.join(BASE_DIR, "Fonts", font_file)
        if os.path.exists(font_path):
            return font_path.replace("\\", "/")
    
    # Try direct file search
    fonts_dir = os.path.join(BASE_DIR, "Fonts")
    if os.path.isdir(fonts_dir):
        # Search for font files containing the family name
        font_files = []
        for file in os.listdir(fonts_dir):
            if file.lower().endswith(('.ttf', '.otf')):
                if font_family_lower in file.lower():
                    font_files.append(os.path.join(fonts_dir, file))
        
        if font_files:
            # Return the first found font
            return font_files[0].replace("\\", "/")
    
    # Ultimate fallback to arial
    font_path = os.path.join(BASE_DIR, "Fonts", "arial.ttf")
    if os.path.exists(font_path):
        return font_path.replace("\\", "/")
    
    # If arial doesn't exist, return empty string (FFmpeg will use default)
    return ""

def compute_line_spacing(line_height, font_size):
    """
    Calculate line spacing based on line-height value.
    Handles: 'normal', '24px', '1.5', 1.2, etc.
    Returns: spacing value in pixels (can be negative for tight spacing)
    """
    if line_height in (None, "", "normal"):
        # Browser default 'normal' is typically 1.2em
        return int(font_size * 1.2 - font_size)  # Returns spacing between lines
    
    try:
        if isinstance(line_height, str):
            # Remove 'px' if present
            line_height = line_height.strip().lower()
            if line_height.endswith("px"):
                px_val = float(line_height.replace("px", ""))
                return int(px_val - font_size)  # Return spacing (total height - font_size)
            elif line_height == "normal":
                return int(font_size * 0.2)  # 1.2em - 1em = 0.2em spacing
        
        # Handle numeric values (em-based or unitless)
        val = float(line_height)
        if val < 1:  # Too small, probably invalid
            return int(font_size * 0.2)
        elif val < 3:  # Likely em-based (1.2, 1.5, etc.)
            return int(font_size * val - font_size)
        else:  # Pixel value
            return int(val - font_size)
            
    except Exception:
        # Fallback to reasonable default
        return int(font_size * 0.2)

def wrap_text(
    text,
    max_width,
    font_size,
    letter_spacing,
    word_wrap,
    word_break,
    canvas_width=None,
):
    if not text or font_size <= 0:
        return text
    
    if max_width is None:
        max_width = 0

    # FIX: Ensure canvas_width is properly handled
    if max_width and max_width > 0:
        effective_width = max_width
    else:
        # Fallback ONLY when width is missing
        # FIX: Ensure canvas_width is not None
        # canvas_width_val = canvas_width or 1920  # Default if None
        effective_width = int((canvas_width or 1920) * 0.7)

    avg_char = max(
        1.0,
        (font_size * 0.6) + max(0.0, letter_spacing * 0.5)
    )

    max_chars = max(1, int(effective_width / avg_char))
    allow_break = str(word_wrap).lower() in ("break-word", "anywhere") or str(word_break).lower() in ("break-all", "break-word", "anywhere")
    break_all = str(word_break).lower() == "break-all"
    lines = []
    for para in text.splitlines():
        if not para:
            lines.append("")
            continue
        if break_all:
            for i in range(0, len(para), max_chars):
                lines.append(para[i:i + max_chars])
            continue
        words = para.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            if len(word) > max_chars and allow_break:
                for i in range(0, len(word), max_chars):
                    chunk = word[i:i + max_chars]
                    if len(chunk) == max_chars:
                        lines.append(chunk)
                    else:
                        current = chunk
            else:
                current = word
        if current:
            lines.append(current)
    return "\n".join(lines)

def parse_shadow_string(value):
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v or v.lower() == "none":
        return None
    parts = v.replace(",", " ").split()
    nums = []
    color = None
    for part in parts:
        if part.endswith("px") or PX_RE.match(part):
            try:
                nums.append(parse_px(part))
            except Exception:
                continue
        elif part.startswith("#") or part.lower().startswith("rgb"):
            color = part
    if len(nums) >= 2 and (nums[0] != 0 or nums[1] != 0):
        return {"x": nums[0], "y": nums[1], "color": color or "#000000"}
    return None

def add_text_item_filters(filter_parts, last_label, item, duration, text_idx, canvas_w=None, canvas_h=None):
    details = item.get("details", {})
    display = item.get("display", {})
    
    start = display.get("from", 0) / 1000
    end = display.get("to", duration * 1000) / 1000
    
    scale_val = parse_scale(details.get("transform", "scale(1)"))
    raw_text = details.get("text", "")
    font_size = int(details.get("fontSize", 40) * scale_val)
    font_size = min(font_size, 200)  # Limit to 200px maximum
    opacity = float(details.get("opacity", 100)) / 100.0
    letter_spacing = parse_px(details.get("letterSpacing", 0)) if details.get("letterSpacing") not in (None, "normal") else 0.0
    letter_spacing = letter_spacing * scale_val
    line_spacing = compute_line_spacing(details.get("lineHeight", "normal"), font_size)
    
    # FIX: Properly initialize max_width with proper scoping
    raw_width = details.get("width")
    max_width = 0  # Initialize first
    
    try:
        if raw_width not in (None, "", 0, "0", "0px"):
            max_width = float(parse_px(raw_width)) * scale_val
    except Exception as e:
        print(f"Warning: Could not parse width '{raw_width}': {e}")
        max_width = 0.0
    # Don't multiply again - that was causing the issue
    # if max_width:
    #     max_width = max_width * scale_val  # REMOVE THIS LINE
    
    word_wrap = details.get("wordWrap", "normal")
    word_break = details.get("wordBreak", "normal")

      # DEBUG: Print values to see what's happening
    print(f"DEBUG: raw_text={raw_text[:50] if raw_text else ''}, max_width={max_width}, font_size={font_size}")
    
    # Now max_width is properly initialized
    wrapped_text = wrap_text(
        raw_text,
        max_width,
        font_size,
        letter_spacing,
        word_wrap,
        word_break,
        canvas_width=canvas_w,  # Use canvas_w parameter
    )
    
    textfile_path = ""
    try:
        textfile_path = write_text_temp(wrapped_text)
    except Exception:
        textfile_path = ""
    
    text = ffmpeg_escape_text(wrapped_text)
    
    left = parse_px(details.get("left", 0))
    top = parse_px(details.get("top", 0))
    text_box_w = parse_px(details.get("width", 0)) * scale_val if details.get("width") else 0
    text_box_h = parse_px(details.get("height", 0)) * scale_val if details.get("height") else 0
    
    if text_box_w:
        left = left + (parse_px(details.get("width", 0)) - text_box_w) / 2
    if text_box_h:
        top = top + (parse_px(details.get("height", 0)) - text_box_h) / 2
    
    align = str(details.get("textAlign", "left")).lower()
    
    if max_width > 0 and align in ("center", "right"):
        if align == "center":
            x_expr = f"{left}+({max_width}-text_w)/2"
        else:
            x_expr = f"{left}+{max_width}-text_w"
    else:
        x_expr = f"{left}"  
    
    if text_box_h:
        y_expr = f"{top} + ({text_box_h} - text_h)/2"
    else:
        y_expr = f"{top}"
    
    font_path = resolve_font_file(details)
    text_color = ffmpeg_color(parse_color(details.get("color", "#ffffff")), opacity)
    bg_color = parse_color(details.get("backgroundColor", "transparent"))
    bg_color_str = ffmpeg_color(bg_color, opacity)
    
    text_source = f"text='{text}'"
    if textfile_path:
        text_source = f"textfile='{ffmpeg_escape_path(textfile_path)}'"
    
    base_params = [
        f"fontfile='{ffmpeg_escape_path(font_path)}'",
        text_source,
        f"x={x_expr}",
        f"y={y_expr}",
        f"fontsize={font_size}",
        f"fontcolor={text_color}",
        "fix_bounds=1"
    ]
    
    if letter_spacing:
        base_params.append(f"letter_spacing={int(letter_spacing)}")
    
    if line_spacing is not None:
        base_params.append(f"line_spacing={int(line_spacing)}")
    
    if bg_color[3] > 0:
        base_params.append("box=1")
        base_params.append(f"boxcolor={bg_color_str}")
    
    border_width = details.get("borderWidth", 0)
    border_color = details.get("borderColor", "transparent")
    if border_width and border_color and border_color != "transparent":
        base_params.append(f"borderw={int(border_width)}")
        base_params.append(f"bordercolor={ffmpeg_color(parse_color(border_color), opacity)}")
    
    shadows = []
    text_shadow = parse_shadow_string(details.get("textShadow", "none"))
    if text_shadow:
        text_shadow["x"] = text_shadow.get("x", 0) * scale_val
        text_shadow["y"] = text_shadow.get("y", 0) * scale_val
        shadows.append(text_shadow)
    
    box_shadow = details.get("boxShadow")
    if isinstance(box_shadow, dict):
        shadow_color = box_shadow.get("color", "#000000")
        shadow_x = box_shadow.get("x", 0) * scale_val
        shadow_y = box_shadow.get("y", 0) * scale_val
        if shadow_x or shadow_y:
            shadows.append({
                "x": shadow_x,
                "y": shadow_y,
                "color": shadow_color,
            })
    
    current_label = last_label
    for s_idx, shadow in enumerate(shadows):
        shadow_x = shadow.get("x", 0) if shadow else 0
        shadow_y = shadow.get("y", 0) if shadow else 0
        shadow_color = ffmpeg_color(parse_color(shadow.get("color", "#000000")), opacity)
        shadow_label = f"[txt_shadow{text_idx}_{s_idx}]"
        shadow_params = [
            f"fontfile='{ffmpeg_escape_path(font_path)}'",
            text_source,
            f"x=({x_expr})+{shadow_x}",
            f"y=({y_expr})+{shadow_y}",
            f"fontsize={font_size}",
            f"fontcolor={shadow_color}",
        ]
        
        if letter_spacing:
            shadow_params.append(f"letter_spacing={int(letter_spacing)}")
        if line_spacing is not None:
            shadow_params.append(f"line_spacing={int(line_spacing)}")
        
        filter_parts.append(
            f"{current_label}drawtext={':'.join(shadow_params)}:enable='between(t,{start},{end})'{shadow_label}"
        )
        current_label = shadow_label
    
    out_label = f"[out_txt{text_idx}]"
    filter_parts.append(
        f"{current_label}drawtext={':'.join(base_params)}:enable='between(t,{start},{end})'{out_label}"
    )
    
    return out_label, text_idx + 1

# ---------------------------------------------------------
# MAIN RENDER FUNCTION
# ---------------------------------------------------------

def generate_ffmpeg_cmd(template):
    design = template['template_json']['design']
    track_map = design['trackItemsMap']
    duration = template.get('duration', 10)
    canvas_w, canvas_h = resolve_canvas_size(design)
    
    filter_parts = []
    input_files = []
    map_audio = []
    
    # 1️⃣ Base black canvas
    filter_parts.append(f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base];")
    last_label = "[base]"
    
    # 2️⃣ Process all video items
    video_labels = []
    for idx, vid_id in enumerate([tid for tid in design['trackItemIds'] if track_map[tid]['type']=='video']):
        item = track_map[vid_id]
        path = item['details']['src']
        input_files.append(path)
        start = item.get('display', {}).get('from', 0)/1000
        end = item.get('display', {}).get('to', duration*1000)/1000
        scale_factor = parse_scale(item['details'].get('transform', 'scale(1)'))
        orig_w = float(item['details'].get('width', canvas_w))
        orig_h = float(item['details'].get('height', canvas_h))
        scaled_w = orig_w * scale_factor
        scaled_h = orig_h * scale_factor
        left = float(parse_px(item['details'].get('left', 0)))
        top = float(parse_px(item['details'].get('top', 0)))
        left = left + (orig_w - scaled_w) / 2
        top = top + (orig_h - scaled_h) / 2
        filter_parts.append(f"[{idx}:v]scale={scaled_w}:{scaled_h},setpts=PTS-STARTPTS[v{idx}];")
        filter_parts.append(f"{last_label}[v{idx}]overlay={left}:{top}:enable='between(t,{start},{end})'[o{idx}];")
        last_label = f"[o{idx}]"
        video_labels.append(last_label)
    
    # 3️⃣ Process all text items
    text_items = [tid for tid in design['trackItemIds'] if track_map[tid]['type']=='text']
    txt_count = 0
    for idx, txt_id in enumerate(text_items):
        item = track_map[txt_id]
        item["details"]["_canvas_width"] = canvas_w
        last_label, txt_count = add_text_item_filters(
            filter_parts,
            last_label,
            item,
            duration,
            txt_count,
        )
    
    # 4️⃣ Process all image items
    image_items = [tid for tid in design['trackItemIds'] if track_map[tid]['type']=='image']
    for idx, img_id in enumerate(image_items):
        item = track_map[img_id]
        path = item['details']['src']
        input_files.append(path)
        start = item['display']['from']/1000
        end = item['display']['to']/1000
        scale_x = parse_scale(item['details'].get('transform', 'scale(1)'))
        orig_w = float(item['details'].get('width', 0) or canvas_w)
        orig_h = float(item['details'].get('height', 0) or canvas_h)
        scaled_w = orig_w * scale_x
        scaled_h = orig_h * scale_x
        x = float(parse_px(item['details'].get('left', 0)))
        y = float(parse_px(item['details'].get('top', 0)))
        x = x + (orig_w - scaled_w) / 2
        y = y + (orig_h - scaled_h) / 2
        filter_parts.append(f"[{len(video_labels)+idx}:v]scale={scaled_w}:{scaled_h},setpts=PTS-STARTPTS[vimg{idx}];")
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
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(resolve_fps(design))]
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

def normalize_media_src(src: str) -> str:
    if not src:
        return ""
    if isinstance(src, str) and src.startswith("http"):
        return src
    return abs_media_path(src)

def write_text_temp(text: str) -> str:
    ensure_dir(MEDIA_ROOT)
    name = f"text_{uuid.uuid4().hex}.txt"
    path = os.path.abspath(os.path.join(MEDIA_ROOT, name))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text or "")
    return path

def to_even(value, min_value=2):
    try:
        v = int(round(float(value)))
    except Exception:
        v = min_value
    if v < min_value:
        v = min_value
    if v % 2 != 0:
        v += 1
    return v

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

def safe_float(val):
    """Handles '10px', '0.32, 0.32', and None values safely."""
    if val is None: return 0.0
    try:
        clean_val = str(val).replace("px", "").split(',')[0].strip()
        return float(clean_val)
    except (ValueError, IndexError):
        return 0.0

def render_preview(template, output_path):
    design = template.get("template_json", {}).get("design", {})
    track_items_map = design.get("trackItemsMap", {})
    tracks = design.get("tracks", [])
    duration = float(template.get("duration", 10))
    canvas_w, canvas_h = resolve_canvas_size(design)
    fps = resolve_fps(design)
    
    filter_parts = []
    visual_inputs = [] 
    audio_inputs = []  
    
    # 1. Base Layer (Background Canvas)
    filter_parts.append(f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base]")
    last_label = "[base]"

    # 2. SEPARATE INPUTS (Videos, Images, Audio) with stable order
    track_item_ids = design.get("trackItemIds", [])
    ordered_visual_ids = [tid for tid in track_item_ids if track_items_map.get(tid, {}).get("type") in ["video", "image"]]

    if ordered_visual_ids:
        for item_id in ordered_visual_ids:
            item = track_items_map.get(item_id, {})
            details = item.get("details", {})
            src = details.get("src", "")
            if not src:
                continue
            abs_src = normalize_media_src(src)
            if not abs_src.startswith("http"):
                ensure_file_exists(abs_src)
            visual_inputs.append({"src": abs_src, "item": item, "media_type": item.get("type")})
    else:
        for track in tracks:
            itype = track.get("type")
            for item_id in track.get("items", []):
                item = track_items_map.get(item_id, {})
                details = item.get("details", {})
                src = details.get("src", "")
                if not src:
                    continue
                if itype in ["video", "image"] or item.get("type") in ["video", "image"]:
                    abs_src = normalize_media_src(src)
                    if not abs_src.startswith("http"):
                        ensure_file_exists(abs_src)
                    media_type = item.get("type") or itype
                    visual_inputs.append({"src": abs_src, "item": item, "media_type": media_type})
                elif itype == "audio":
                    abs_src = normalize_media_src(src)
                    if not abs_src.startswith("http"):
                        ensure_file_exists(abs_src)
                    audio_inputs.append({"src": abs_src, "item": item})

    if tracks:
        for track in tracks:
            if track.get("type") == "audio":
                for item_id in track.get("items", []):
                    item = track_items_map.get(item_id, {})
                    details = item.get("details", {})
                    src = details.get("src", "")
                    if not src:
                        continue
                    abs_src = normalize_media_src(src)
                    if not abs_src.startswith("http"):
                        ensure_file_exists(abs_src)
                    audio_inputs.append({"src": abs_src, "item": item})

    # 3. BUILD VISUAL FILTERS (Videos & Images)
    for idx, data in enumerate(visual_inputs):
        item, details = data["item"], data["item"].get("details", {})
        display = item.get("display", {})
        start, end = display.get("from", 0)/1000, display.get("to", duration*1000)/1000
        
        # Scale handling (fix comma error)
        scale_val = parse_scale(details.get("transform", "scale(1)"))

        # Scaling and Positioning (center-origin scaling like editor)
        orig_w = safe_float(details.get("width", canvas_w))
        orig_h = safe_float(details.get("height", canvas_h))
        tw = to_even(orig_w * scale_val)
        th = to_even(orig_h * scale_val)
        left = safe_float(details.get("left", 0))
        top = safe_float(details.get("top", 0))
        left = left + (orig_w - tw) / 2
        top = top + (orig_h - th) / 2

        scaled, overlaid = f"sc{idx}", f"ov{idx}"
        filter_parts.append(f"[{idx}:v]scale={tw}:{th},setpts=PTS-STARTPTS+{start}/TB[{scaled}]")
        filter_parts.append(f"{last_label}[{scaled}]overlay={left}:{top}:enable='between(t,{start},{end})'[{overlaid}]")
        last_label = f"[{overlaid}]"

    # 4. HANDLE TEXT (Dynamic JSON Styles)
    txt_idx = 0
    for track in tracks:
        if track.get("type") == "text":
            for item_id in track.get("items", []):
                item = track_items_map.get(item_id, {})
                last_label, txt_idx = add_text_item_filters(
                    filter_parts,
                    last_label,
                    item,
                    duration,
                    txt_idx,
                    canvas_w=canvas_w,  # Add canvas dimensions
                    canvas_h=canvas_h,
                )

    # 5. AUDIO MIXING (video + external)
    audio_mix_filter = ""
    audio_sources = []
    for i, v in enumerate(visual_inputs):
        if (v.get("media_type") or "").lower() == "video":
            display = v["item"].get("display", {})
            a_start = int(display.get("from", 0))
            vol = safe_float(v["item"].get("details", {}).get("volume", 100)) / 100.0
            audio_sources.append({"index": i, "start_ms": a_start, "volume": vol})
    for i, a in enumerate(audio_inputs):
        idx = len(visual_inputs) + i
        a_start = int(a["item"].get("display", {}).get("from", 0))
        vol = safe_float(a["item"].get("details", {}).get("volume", 100)) / 100.0
        audio_sources.append({"index": idx, "start_ms": a_start, "volume": vol})

    if audio_sources:
        a_labels = ""
        for i, src in enumerate(audio_sources):
            a_start = max(0, int(src["start_ms"]))
            volume = src["volume"]
            vol_filter = f",volume={volume:.3f}" if volume != 1.0 else ""
            a_labels += f"[{src['index']}:a]adelay={a_start}|{a_start}{vol_filter},aresample=async=1:first_pts=0[aud{i}];"
        audio_mix_filter = (
            f"{a_labels}" + "".join([f"[aud{i}]" for i in range(len(audio_sources))]) +
            f"amix=inputs={len(audio_sources)}:normalize=0[outa]"
        )

    # 6. EXECUTION
    cmd = ["ffmpeg", "-y"]
    for v in visual_inputs:
        if (v.get("media_type") or "").lower() == "image":
            cmd += ["-loop", "1", "-t", str(duration), "-i", v["src"]]
        else:
            cmd += ["-i", v["src"]]
    for a in audio_inputs:
        cmd += ["-i", a["src"]]

    full_filter = ";".join(filter_parts)
    if audio_mix_filter:
        full_filter += ";" + audio_mix_filter
        cmd += ["-filter_complex", full_filter, "-map", last_label, "-map", "[outa]"]
    else:
        cmd += ["-filter_complex", full_filter, "-map", last_label]

    if audio_mix_filter:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-t", str(duration), output_path]
    else:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), "-an", "-t", str(duration), output_path]
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

    print("SIMPLE CMD:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    return output_path