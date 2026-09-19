import os
import subprocess
import shlex
import shutil
from typing import Dict, Any, Optional
import uuid 
import re 
import urllib.parse 
import requests 
import hashlib 
import shlex
import logging
from bson import ObjectId 
from app.db.connection import db 
from dotenv import load_dotenv
load_dotenv()
from app.services.render_helper import (
    find_background,
)
from app.services.storage import ensure_media_folder, get_media_abs_path, template_folder_path
from app.utils.placeholders import replace_placeholders
from app.services.render_queue import current_render_job_id, current_render_temp_dir
# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
DEBUG = os.getenv("DEBUG", "False").lower() == "true" 
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media")
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


FFMPEG_THREADS = _env_int("FFMPEG_THREADS", 1)

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
FONT_PATH = os.path.join(BASE_DIR, "Fonts", "arial.ttf")
FONT_PATH = FONT_PATH.replace("\\", "/")
PX_RE = re.compile(r"-?\d+(\.\d+)?")
FONT_CACHE_DIR = os.path.join(MEDIA_ROOT, "font_cache")
logger = logging.getLogger(__name__)
_DRAWTEXT_TEXT_ALIGN_SUPPORTED: Optional[bool] = None

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

def ensure_file_exists(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Media file not found: {path}")

# ---------------------------------------------------------
# ✅ NEW: Central src validation — used in ALL render paths
# ---------------------------------------------------------
def is_valid_src(src: str, label: str = "") -> bool:
    """
    Returns True only if src is a non-empty string that points to either:
      - A remote URL (http/https) — assumed valid, FFmpeg will handle errors
      - A local file path that actually exists on disk

    Rejects:
      - None / empty string
      - Unresolved placeholders like {{customer.logo_url}}
      - Local paths that don't exist on disk
    """
    if not src or not isinstance(src, str):
        print(f"   ⏭ Skipping {label}: src is empty or None")
        return False

    src = src.strip()

    # Unresolved placeholder — placeholder replacement found no value
    if src.startswith("{{") or src.endswith("}}"):
        print(f"   ⏭ Skipping {label}: unresolved placeholder → {src}")
        return False

    # Remote URL — trust FFmpeg to handle it
    if src.startswith("http://") or src.startswith("https://"):
        return True

    # Local file — must actually exist
    if not os.path.exists(src):
        print(f"   ⏭ Skipping {label}: local file not found → {src}")
        return False

    return True

def has_audio_stream(src: str) -> bool:
    try:
        cmd = [
            FFPROBE,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            src,
        ]
        result = _run_with_resolved_exec(cmd, exec_name="ffprobe", env_var="FFPROBE_BIN", capture_output=True, text=True)
        return result.returncode == 0 and result.stdout.strip() != ""
    except Exception:
        return False

# Placeholder replacement is centralized in app/utils/placeholders.py

def parse_position(value):
    if isinstance(value, str):
        value = value.strip().replace("px", "")
    try:
        return float(value)
    except Exception:
        return 0.0

def parse_px(value):
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
            .replace("\n", "\\n")
            .replace(":", "\\:")
            .replace("'", "\\'")
            .replace("%", "\\%")
            .replace("[", "\\[")
            .replace("]", "\\]")
    )


def _resolve_exec(exec_name: str, env_var: str | None = None) -> str | None:
    """Return full path for executable or None if not found."""
    if env_var:
        val = os.getenv(env_var)
        if val:
            return val
    found = shutil.which(exec_name)
    if found:
        return found
    return None


def _run_with_resolved_exec(cmd, exec_name: str = "ffmpeg", env_var: str | None = None, **kwargs):
    """Replace cmd[0] with resolved executable path and run subprocess."""
    path = _resolve_exec(exec_name, env_var)
    if not path:
        ev = env_var or f"{exec_name.upper()}_BIN"
        raise FileNotFoundError(
            f"Required executable '{exec_name}' not found. Install '{exec_name}' on the server or set the environment variable {ev} to its full path."
        )
    cmd = list(cmd)
    cmd[0] = path
    if exec_name == "ffmpeg":
        cmd[1:1] = [
            "-hide_banner",
            "-nostdin",
            "-threads", str(FFMPEG_THREADS),
            "-filter_threads", str(FFMPEG_THREADS),
        ]
        env = dict(os.environ)
        env.setdefault("OMP_NUM_THREADS", str(FFMPEG_THREADS))
        env.setdefault("MKL_NUM_THREADS", str(FFMPEG_THREADS))
        kwargs.setdefault("env", env)
    job_id = current_render_job_id.get()
    if job_id:
        logger.info("[render] job_id=%s running %s", job_id, exec_name)
    return subprocess.run(cmd, **kwargs)

def ffmpeg_drawtext_supports_text_align() -> bool:
    """Return whether this FFmpeg build supports drawtext's text_align option."""
    global _DRAWTEXT_TEXT_ALIGN_SUPPORTED
    if _DRAWTEXT_TEXT_ALIGN_SUPPORTED is not None:
        return _DRAWTEXT_TEXT_ALIGN_SUPPORTED

    path = _resolve_exec("ffmpeg", "FFMPEG_BIN")
    if not path:
        _DRAWTEXT_TEXT_ALIGN_SUPPORTED = False
        return False

    try:
        result = subprocess.run(
            [path, "-hide_banner", "-h", "filter=drawtext"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        help_text = f"{result.stdout}\n{result.stderr}"
        _DRAWTEXT_TEXT_ALIGN_SUPPORTED = "text_align" in help_text
    except Exception:
        _DRAWTEXT_TEXT_ALIGN_SUPPORTED = False

    return _DRAWTEXT_TEXT_ALIGN_SUPPORTED

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
    font_family_lower = str(font_family).lower()
    
    font_mappings = {
        "arial": "arial.ttf",
        "helvetica": "arial.ttf",
        "times new roman": "times.ttf",
        "times": "times.ttf",
        "courier new": "cour.ttf",
        "verdana": "verdana.ttf",
        "tahoma": "tahoma.ttf",
        "georgia": "georgia.ttf",
    }
    
    if font_family_lower in font_mappings:
        font_file = font_mappings[font_family_lower]
        font_path = os.path.join(BASE_DIR, "Fonts", font_file)
        if os.path.exists(font_path):
            return font_path.replace("\\", "/")
    
    fonts_dir = os.path.join(BASE_DIR, "Fonts")
    if os.path.isdir(fonts_dir):
        font_files = []
        for file in os.listdir(fonts_dir):
            if file.lower().endswith(('.ttf', '.otf')):
                if font_family_lower in file.lower():
                    font_files.append(os.path.join(fonts_dir, file))
        if font_files:
            return font_files[0].replace("\\", "/")
    
    font_path = os.path.join(BASE_DIR, "Fonts", "arial.ttf")
    if os.path.exists(font_path):
        return font_path.replace("\\", "/")
    
    return ""

from typing import Optional

def compute_line_spacing(line_height, font_size):
    try:
        font_size = float(font_size)
    except Exception:
        return -75

    # Very tight spacing
    return int(-(font_size * 0.65))

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

    text = text.strip()
    if not text:
        return text

    if max_width is None:
        max_width = 0

    if max_width and max_width > 0:
        effective_width = max_width
    else:
        effective_width = int((canvas_width or 1920) * 0.7)

    avg_char = max(
        1.0,
        (font_size * 0.68) + max(0.0, letter_spacing)
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

def smart_logo_mapping(src: str, size: str = None) -> str:
    if not isinstance(src, str):
        return src
    
    if src.startswith("{{") and src.endswith("}}"):
        return src
    
    if "placehold.co" in src.lower():
        if "300x150" in src or "300" in src:
            return "{{customer.logo_url}}"
        elif "400x200" in src or "400" in src:
            return "{{company.logo_url}}"
        return "{{company.logo_url}}"
    
    return src

def add_text_item_filters(filter_parts, last_label, item, duration, text_idx, context, canvas_w=None, canvas_h=None):
    details = item.get("details", {}) or {}
    display = item.get("display", {})
    start = display.get("from", 0) / 1000
    end = display.get("to", duration * 1000) / 1000

    scale_val = parse_scale(details.get("transform", "scale(1)"))
    raw_text = item.get("details", {}).get("text", "")

    if context and isinstance(context, dict):
        raw_text = replace_placeholders(raw_text, context)

    transform = str(details.get("textTransform", "none")).lower()
    if transform == "uppercase":
        raw_text = raw_text.upper()
    elif transform == "lowercase":
        raw_text = raw_text.lower()
    elif transform in ("capitalize", "title"):
        raw_text = raw_text.title()

    font_size = int(details.get("fontSize", 40) * scale_val)
    font_size = min(font_size, 200)

    opacity = float(details.get("opacity", 100)) / 100.0
    
    letter_spacing = 0
    if details.get("letterSpacing") not in (None, "normal"):
        letter_spacing = parse_px(details.get("letterSpacing", 0)) * scale_val

    raw_line_height = details.get("lineHeight", details.get("line-height", "normal"))
    line_spacing = compute_line_spacing(raw_line_height, font_size)

    raw_width = details.get("width")
    max_width = 0
    try:
        if raw_width not in (None, "", 0, "0", "0px"):
            max_width = float(parse_px(raw_width)) * scale_val
    except:
        max_width = 0

    word_wrap = details.get("wordWrap", "normal")
    word_break = details.get("wordBreak", "normal")

    wrapped_text = wrap_text(
        raw_text,
        max_width,
        font_size,
        letter_spacing,
        word_wrap,
        word_break,
        canvas_width=canvas_w,
    )

    
    raw_height = details.get("height")
    if raw_height:
        try:
            max_height = float(parse_px(raw_height)) * scale_val

            # Get lineHeight multiplier (CSS default "normal" ≈ 1.2)
            raw_lh = raw_line_height
            if raw_lh in ("normal", "", None) or (
                isinstance(raw_lh, str) and raw_lh.strip().lower() in ("normal", "auto", "inherit")
            ):
                lh_multiplier = 1.2
            else:
                try:
                    rs = str(raw_lh).strip()
                    if rs.endswith("%"):
                        lh_multiplier = float(rs[:-1].strip()) / 100.0
                    else:
                        lh_val = float(rs.replace("px", "").strip())
                        lh_multiplier = lh_val if lh_val <= 4 else lh_val / font_size
                except Exception:
                    lh_multiplier = 1.2

            effective_line_h = font_size * lh_multiplier

            # Only clamp if height is meaningfully larger than one line
            # (avoids clamping when height is just auto/single-line default)
            min_multiline_height = effective_line_h * 1.8
            if max_height >= min_multiline_height:
                max_lines = max(1, int(max_height / effective_line_h))
                lines = wrapped_text.splitlines()
                if len(lines) > max_lines:
                    wrapped_text = "\n".join(lines[:max_lines])
            # else: height looks like single-line default — don't clamp, let it wrap freely

        except Exception:
            pass

    textfile_path = ""
    try:
        textfile_path = write_text_temp(wrapped_text)
    except Exception:
        textfile_path = ""

    text = ffmpeg_escape_text(wrapped_text)

    left = parse_px(details.get("left", 0))
    top = parse_px(details.get("top", 0))

    align = str(details.get("textAlign", "left")).lower()

    box_w = max_width if max_width > 0 else (float(canvas_w or 1920) - left)

    if align == "center":
        x_expr = f"{left}+({box_w}-text_w)/2"
    elif align == "right" and box_w > 0:
        x_expr = f"{left}+{box_w}-text_w"
    else:
        x_expr = f"{left}"

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
        "text_shaping=1",
        "fix_bounds=1"
    ]

    if ffmpeg_drawtext_supports_text_align():
        if align == "center":
            base_params.append("text_align=center")
        elif align == "right":
            base_params.append("text_align=right")
        else:
            base_params.append("text_align=left")

    if letter_spacing:
        base_params.append(f"letter_spacing={int(letter_spacing)}")

    # Omit line_spacing when None — "normal" uses font native leading (no double spacing).
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

def parse_scale(transform_str: str) -> float:
    if not transform_str or transform_str == "none":
        return 1.0
    try:
        inner = transform_str.replace("scale(", "").replace(")", "")
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
    temp_dir = current_render_temp_dir.get() or MEDIA_ROOT
    ensure_dir(temp_dir)
    name = f"text_{uuid.uuid4().hex}.txt"
    path = os.path.abspath(os.path.join(temp_dir, name))
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
    if isinstance(value, str):
        clean_val = value.replace('px', '').split(',')[0].strip()
        try:
            return float(clean_val)
        except:
            return 0.0
    return float(value) if value is not None else 0.0

def resolve_overlay_position(details: dict, orig_w: float, orig_h: float, scaled_w: float, scaled_h: float):
    """
    Convert editor position data into FFmpeg overlay x/y expressions.

    When an item is scaled, the editor keeps the scaled media centered inside
    its original box. Apply that same center offset from whichever edge is used.
    """
    if not isinstance(details, dict):
        details = {}

    position = get_object_position(details)
    x_offset = (orig_w - scaled_w) / 2
    y_offset = (orig_h - scaled_h) / 2

    left = safe_float(details.get("left", 0)) + x_offset
    top = safe_float(details.get("top", 0)) + y_offset
    right = safe_float(details.get("right", 0)) + x_offset
    bottom = safe_float(details.get("bottom", 0)) + y_offset

    if "right" in position:
        x_expr = f"W-w-({right})"
    elif position in ("center", "middle", "center-center"):
        x_expr = f"(W-w)/2+({left})"
    else:
        x_expr = f"{left}"

    if "bottom" in position:
        y_expr = f"H-h-({bottom})"
    elif position in ("center", "middle", "center-center"):
        y_expr = f"(H-h)/2+({top})"
    else:
        y_expr = f"{top}"

    return x_expr, y_expr

def safe_float(val):
    if val is None: return 0.0
    try:
        clean_val = str(val).replace("px", "").split(',')[0].strip()
        return float(clean_val)
    except (ValueError, IndexError):
        return 0.0

def get_object_fit(details: dict, media_type: str = "") -> str:
    value = (
        details.get("objectFit")
        or details.get("object-fit")
        or details.get("fit")
        or ""
    )
    value = str(value).strip().lower()
    if value in ("cover", "contain", "fill"):
        return value
    if details.get("isBackground") or media_type == "video":
        return "cover"
    return "contain"

def get_object_position(details: dict) -> str:
    value = (
        details.get("objectPosition")
        or details.get("object-position")
        or details.get("position")
        or "center"
    )
    return str(value).replace("_", "-").lower()

def is_box_anchored_position(details: dict) -> bool:
    position = get_object_position(details)
    return any(anchor in position for anchor in ("left", "right", "top", "bottom"))

def resolve_overlay_xy(details: dict, slot_w: float, slot_h: float, render_w: int, render_h: int, center_scaled: bool = False):
    raw_left = safe_float(details.get("left", 0))
    raw_top = safe_float(details.get("top", 0))
    position = get_object_position(details)

    if center_scaled and not is_box_anchored_position(details):
        left = raw_left + (slot_w - render_w) / 2
    elif "right" in position:
        left = raw_left + slot_w - render_w
    else:
        left = raw_left

    if center_scaled and not is_box_anchored_position(details):
        top = raw_top + (slot_h - render_h) / 2
    elif "bottom" in position:
        top = raw_top + slot_h - render_h
    else:
        top = raw_top

    return left, top

def build_positioned_image_filter(slot_w: int, slot_h: int, details: dict, style_chain: str) -> str:
    if not is_box_anchored_position(details):
        return f"scale={slot_w}:{slot_h}:force_original_aspect_ratio=decrease{style_chain}"

    slot_w = max(2, to_even(slot_w))
    slot_h = max(2, to_even(slot_h))
    position = get_object_position(details)
    scale_filter = f"scale={slot_w}:{slot_h}:force_original_aspect_ratio=decrease{style_chain}"

    if "right" in position:
        pad_x = "ow-iw"
    elif "left" in position:
        pad_x = "0"
    else:
        pad_x = "(ow-iw)/2"

    if "bottom" in position:
        pad_y = "oh-ih"
    elif "top" in position:
        pad_y = "0"
    else:
        pad_y = "(oh-ih)/2"

    return f"{scale_filter},format=rgba,pad={slot_w}:{slot_h}:{pad_x}:{pad_y}:color=0x00000000"

def build_cover_visual_filter(slot_w: int, slot_h: int, style_chain: str, details: dict | None = None) -> str:
    slot_w = max(2, to_even(slot_w))
    slot_h = max(2, to_even(slot_h))
    position = get_object_position(details or {})

    if "left" in position:
        crop_x = "0"
    elif "right" in position:
        crop_x = "iw-ow"
    else:
        crop_x = "(iw-ow)/2"

    if "top" in position:
        crop_y = "0"
    elif "bottom" in position:
        crop_y = "ih-oh"
    else:
        crop_y = "(ih-oh)/2"

    return (
        f"scale={slot_w}:{slot_h}:force_original_aspect_ratio=increase,"
        f"crop={slot_w}:{slot_h}:{crop_x}:{crop_y}{style_chain}"
    )

def build_visual_fit_filter(slot_w: int, slot_h: int, details: dict, style_chain: str, media_type: str = "") -> str:
    fit = get_object_fit(details, media_type)
    slot_w = max(2, to_even(slot_w))
    slot_h = max(2, to_even(slot_h))

    if fit == "fill":
        return f"scale={slot_w}:{slot_h}{style_chain}"

    if fit == "cover":
        return build_cover_visual_filter(slot_w, slot_h, style_chain, details)

    return build_positioned_image_filter(slot_w, slot_h, details, style_chain)

def sync_track_item_bounds(design: dict) -> dict:
    if not isinstance(design, dict):
        return design

    canvas_w, canvas_h = resolve_canvas_size(design)
    track_items_map = design.get("trackItemsMap")
    if not isinstance(track_items_map, dict):
        return design

    for item in track_items_map.values():
        if not isinstance(item, dict):
            continue
        details = item.get("details")
        if not isinstance(details, dict):
            continue

        width = safe_float(details.get("width", 0))
        height = safe_float(details.get("height", 0))
        if width <= 0:
            width = float(canvas_w)
        if height <= 0:
            height = float(canvas_h)

        scale = parse_scale(details.get("transform", "scale(1)"))
        render_w = width * scale
        render_h = height * scale
        left = safe_float(details.get("left", 0))
        top = safe_float(details.get("top", 0))

        details["right"] = float(canvas_w) - (left + render_w)
        details["bottom"] = float(canvas_h) - (top + render_h)
        item["details"] = details

    return design


def build_visual_effect_filters_after_scale(details: dict) -> str:
    """
    FFmpeg filters applied after scale (before setpts), matching editor JSON:
      - flipX / flipY
      - blur (details.blur — treated as ~px-ish strength → gblur sigma)
      - brightness (details.brightness — percent, 100 = unchanged; CSS-like multiply via colorchannelmixer)
      - opacity (percent, merged with brightness in one colorchannelmixer when needed)
    """
    if not isinstance(details, dict):
        details = {}

    parts: list[str] = []

    if details.get("flipX"):
        parts.append("hflip")
    if details.get("flipY"):
        parts.append("vflip")

    blur_val = safe_float(details.get("blur", 0))
    if blur_val > 0:
        sigma = min(30.0, max(0.3, blur_val * 0.18))
        parts.append(f"gblur=sigma={sigma:.3f}")

    b_pct = safe_float(details.get("brightness", 100))
    m = max(0.01, min(3.0, b_pct / 100.0))
    op = safe_float(details.get("opacity", 100)) / 100.0
    op = max(0.0, min(1.0, op))

    if abs(m - 1.0) > 0.001 or op < 0.999:
        if op < 0.999:
            parts.append("format=rgba")
        parts.append(
            f"colorchannelmixer=rr={m:.6f}:gg={m:.6f}:bb={m:.6f}:aa={op:.6f}"
        )

    if not parts:
        return ""
    return "," + ",".join(parts)

def render_image_preview(template_json, customer, company, output_path):
    design = template_json.get("design", {}) if isinstance(template_json, dict) else {}
    canvas_w, canvas_h = resolve_canvas_size(design)

    context = {
        "customer": customer or {},
        "company": company or {},
    }

    track_items_map = design.get("trackItemsMap", {}) if isinstance(design, dict) else {}
    track_item_ids = design.get("trackItemIds", []) if isinstance(design, dict) else []
    ordered_ids = track_item_ids if track_item_ids else list(track_items_map.keys())

    bg_item = find_background(template_json)
    if bg_item and bg_item.get("type") != "image":
        bg_item = None

    inputs: list[str] = []
    filter_parts: list[str] = []
    current = "[base]"

    # -------------------------------------------------------
    # Background — ✅ validate before adding to inputs
    # -------------------------------------------------------
    if bg_item:
        bg_src = smart_logo_mapping(bg_item.get("details", {}).get("src", ""))
        bg_src = replace_placeholders(bg_src, context)
        bg_src = normalize_media_src(bg_src) if bg_src else ""

        if is_valid_src(bg_src, label="background"):
            inputs.append(bg_src)
            bg_style = build_visual_effect_filters_after_scale(bg_item.get("details", {}))
            filter_parts.append(
                f"[0:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,"
                f"crop={canvas_w}:{canvas_h}{bg_style}[base]"
            )
        else:
            print(f"   ⚠️ Background src invalid/missing — using black canvas fallback")
            filter_parts.append(f"color=c=black:s={canvas_w}x{canvas_h}[base]")
    else:
        filter_parts.append(f"color=c=black:s={canvas_w}x{canvas_h}[base]")

    # -------------------------------------------------------
    # Image overlays — ✅ FIXED OVERLAY POSITIONING LOGIC
    # -------------------------------------------------------
    overlay_idx = 0
    for item_id in ordered_ids:
        item = track_items_map.get(item_id, {})
        if item.get("type") != "image":
            continue
        details = item.get("details", {})
        if details.get("isBackground"):
            continue

        src = smart_logo_mapping(details.get("src", ""))
        src = replace_placeholders(src, context)
        src = normalize_media_src(src) if src else ""

        if not is_valid_src(src, label=f"image overlay [{item_id}]"):
            continue

        inputs.append(src)
        in_idx = len(inputs) - 1

        scale = parse_scale(details.get("transform", "scale(1)"))
        
        # 🟢 FIX 1: Default fallback width/height 150px/150px rakha hai (Canvas W nahi)
        orig_w = safe_float(details.get("width", canvas_w)) or canvas_w
        orig_h = safe_float(details.get("height", canvas_h)) or canvas_h

        tw = max(2, to_even(orig_w * scale))
        th = max(2, to_even(orig_h * scale))
        x_expr, y_expr = resolve_overlay_position(details, orig_w, orig_h, tw, th)
        box_w = tw
        box_h = th

        # 🟢 FIX 2: Exact left & top positions parse ho rahi hain
        # Scale center adjustment
        left, top = resolve_overlay_xy(details, orig_w, orig_h, box_w, box_h, center_scaled=True)

        style_chain = build_visual_effect_filters_after_scale(details)
        image_filter = build_visual_fit_filter(box_w, box_h, details, style_chain, "image")

        sc = f"[img_sc{overlay_idx}]"
        ov = f"[img_ov{overlay_idx}]"
        filter_parts.append(
          f"[{in_idx}:v]{image_filter},setpts=PTS-STARTPTS{sc}"
        )
        filter_parts.append(
            f"{current}{sc}overlay={x_expr}:{y_expr}{ov}"
        )
        current = ov
        overlay_idx += 1

    # -------------------------------------------------------
    # Text overlays
    # -------------------------------------------------------
    txt_idx = 0
    duration = 1.0
    for item_id in ordered_ids:
        item = track_items_map.get(item_id, {})
        if item.get("type") != "text":
            continue
        if not item.get("details", {}).get("text"):
            continue
        item = dict(item)
        item["display"] = {"from": 0, "to": 1000}
        current, txt_idx = add_text_item_filters(
            filter_parts,
            current,
            item,
            duration,
            txt_idx,
            context,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
        )

    # -------------------------------------------------------
    # FFmpeg execution
    # -------------------------------------------------------
    cmd = ["ffmpeg", "-y"]
    for src in inputs:
        cmd += ["-loop", "1", "-i", src]

    output_path = str(output_path).replace("\\", "/")

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", current,
        "-frames:v", "1",
        "-q:v", "2",
        "-vcodec", "mjpeg",
        "-f", "image2",
        output_path,
    ]

    try:
        print("Render image FFmpeg command:", " ".join(shlex.quote(c) for c in cmd))
    except Exception:
        print("Render image FFmpeg command:", cmd)

    _run_with_resolved_exec(cmd, exec_name="ffmpeg", env_var="FFMPEG_BIN", check=True)
    return " ".join(shlex.quote(c) for c in cmd)

def render_preview(template_json, context_data=None, output_path=None):
    if output_path is None and isinstance(context_data, str):
        output_path = context_data
        context_data = None

    if isinstance(context_data, dict) and "customer" in context_data and "company" in context_data:
        customer = context_data.get("customer")
        company = context_data.get("company")
        context = context_data
    else:
        customer = context_data if isinstance(context_data, dict) else {}
        company = {}
        context = {"customer": customer, "company": company}
    
    if isinstance(template_json, dict) and "template_json" in template_json:
        full_template = template_json
        template_json = full_template.get("template_json", {})
        trim = full_template.get("trim") or {}
        duration = full_template.get("duration")
        if not duration and trim.get("end") is not None:
            duration = float(trim.get("end", 0)) - float(trim.get("start", 0))
    else:
        trim = template_json.get("trim") if isinstance(template_json, dict) else {}
        duration = template_json.get("duration") if isinstance(template_json, dict) else None
        if not duration and isinstance(trim, dict) and trim.get("end") is not None:
            duration = float(trim.get("end", 0)) - float(trim.get("start", 0))

    if not duration or duration <= 0:
        duration = 10

    design = template_json.get("design", {}) if isinstance(template_json, dict) else {}
    track_items_map = design.get("trackItemsMap", {})
    tracks = design.get("tracks", [])
    duration = float(duration)

    canvas_w, canvas_h = resolve_canvas_size(design)
    fps = resolve_fps(design)

    filter_parts = []
    visual_inputs = []
    audio_inputs = []

    # -------------------------------------------------
    # 1️⃣ COLLECT INPUTS — ✅ validate src before adding
    # -------------------------------------------------
    track_item_ids = design.get("trackItemIds", [])
    ordered_visual_ids = [tid for tid in track_item_ids if track_items_map.get(tid, {}).get("type") in ["video", "image"]]

    def _collect_visual(item_id, fallback_type=None):
        """Resolve, validate and return a visual input dict, or None to skip."""
        item = track_items_map.get(item_id, {})
        details = item.get("details", {})
        item_type = item.get("type") or fallback_type or "unknown"

        src_raw = details.get("src", "")
        src_raw = smart_logo_mapping(src_raw)
        src = replace_placeholders(src_raw, context)
        src = normalize_media_src(src) if src else ""

        # ✅ Central validation — skips empty, placeholders, missing files
        if not is_valid_src(src, label=f"{item_type} [{item_id}]"):
            return None

        return {"src": src, "item": item, "media_type": item_type}

    def _collect_audio(item_id, fallback_type=None):
        """Resolve, validate and return an audio input dict, or None to skip."""
        item = track_items_map.get(item_id, {})
        details = item.get("details", {})
        src_raw = details.get("src", "")
        src = replace_placeholders(src_raw, context)
        src = normalize_media_src(src) if src else ""

        # ✅ Central validation
        if not is_valid_src(src, label=f"audio [{item_id}]"):
            return None

        return {"src": src, "item": item}

    if ordered_visual_ids:
        for item_id in ordered_visual_ids:
            result = _collect_visual(item_id)
            if result:
                visual_inputs.append(result)

        for item_id in track_item_ids:
            item = track_items_map.get(item_id, {})
            if item.get("type") != "audio":
                continue
            result = _collect_audio(item_id)
            if result:
                audio_inputs.append(result)
    else:
        for track in tracks:
            ttype = track.get("type")
            for item_id in track.get("items", []):
                if ttype in ["video", "image"]:
                    result = _collect_visual(item_id, fallback_type=ttype)
                    if result:
                        visual_inputs.append(result)
                elif ttype == "audio":
                    result = _collect_audio(item_id)
                    if result:
                        audio_inputs.append(result)

    # -------------------------------------------------
    # 2️⃣ BASE CANVAS
    # -------------------------------------------------
    filter_parts.append(
        f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base]"
    )
    last_label = "[base]"

    # -------------------------------------------------
    # 3️⃣ VISUAL FILTERS
    # -------------------------------------------------
    for idx, data in enumerate(visual_inputs):
        item = data["item"]
        details = item.get("details", {})
        display = item.get("display", {})

        start = display.get("from", 0) / 1000
        end = display.get("to", duration * 1000) / 1000

        # Old Code

        # scale = parse_scale(details.get("transform", "scale(1)"))
        # orig_w = safe_float(details.get("width", canvas_w))
        # orig_h = safe_float(details.get("height", canvas_h))

        # tw = to_even(orig_w * scale)
        # th = to_even(orig_h * scale)
        
        # left = safe_float(details.get("left", 0)) + (orig_w - tw) / 2
        # top = safe_float(details.get("top", 0)) + (orig_h - th) / 2
        # Finished old code
        # New Code
        orig_w = safe_float(details.get("width", 0))
        orig_h = safe_float(details.get("height", 0))

        if orig_w <= 0:
            orig_w = 200.0
        if orig_h <= 0:
            orig_h = 200.0

        scale = parse_scale(details.get("transform", "scale(1)"))

        tw = to_even(orig_w * scale)
        th = to_even(orig_h * scale)
        is_image_input = (data.get("media_type") or "").lower() == "image"
        box_w = tw
        box_h = th

        x_expr, y_expr = resolve_overlay_position(details, orig_w, orig_h, box_w, box_h)

        sc = f"sc{idx}"
        ov = f"ov{idx}"

        style_chain = build_visual_effect_filters_after_scale(details)
        media_type = "image" if is_image_input else "video"
        visual_filter = build_visual_fit_filter(box_w, box_h, details, style_chain, media_type)

        filter_parts.append(
            f"[{idx}:v]{visual_filter},setpts=PTS-STARTPTS+{start}/TB[{sc}]"
        )
        filter_parts.append(
            f"{last_label}[{sc}]overlay={x_expr}:{y_expr}:enable='between(t,{start},{end})'[{ov}]"
        )

        last_label = f"[{ov}]"

    # -------------------------------------------------
    # 4️⃣ TEXT FILTERS (from tracks + any text items only in trackItemIds)
    # -------------------------------------------------
    txt_idx = 0
    text_ids_done: set[str] = set()
    for track in tracks:
        if track.get("type") == "text":
            for item_id in track.get("items", []):
                item = track_items_map.get(item_id, {})
                if not item.get("details", {}).get("text"):
                    continue
                last_label, txt_idx = add_text_item_filters(
                    filter_parts,
                    last_label,
                    item,
                    duration,
                    txt_idx,
                    context,
                    canvas_w=canvas_w,
                    canvas_h=canvas_h,
                )
                text_ids_done.add(str(item_id))

    for item_id in track_item_ids:
        sid = str(item_id)
        if sid in text_ids_done:
            continue
        item = track_items_map.get(item_id, {})
        if item.get("type") != "text":
            continue
        if not item.get("details", {}).get("text"):
            continue
        last_label, txt_idx = add_text_item_filters(
            filter_parts,
            last_label,
            item,
            duration,
            txt_idx,
            context,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
        )
        text_ids_done.add(sid)
    # -------------------------------------------------
    # 5️⃣ AUDIO FILTERS
    # -------------------------------------------------
    audio_sources = []
    has_external_audio = len(audio_inputs) > 0

    for i, v in enumerate(visual_inputs):
        if (v.get("media_type") or "").lower() == "video":
            if not has_audio_stream(v["src"]):
                continue
            display = v["item"].get("display", {})
            trim = v["item"].get("trim", {})
            start_ms = int(display.get("from", 0))
            end_ms = int(display.get("to", duration * 1000))
            trim_from = int(trim.get("from", 0))
            trim_to = trim.get("to")
            if trim_to is not None:
                trim_to = int(trim_to)
            vol = safe_float(v["item"].get("details", {}).get("volume", 100)) / 100.0
            if vol <= 0:
                continue
            if has_external_audio and vol > 0.5:
                vol = 0.4
            audio_sources.append({
                "index": i,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "trim_from": trim_from,
                "trim_to": trim_to,
                "volume": vol,
            })

    for i, a in enumerate(audio_inputs):
        idx = len(visual_inputs) + i
        display = a["item"].get("display", {})
        trim = a["item"].get("trim", {})
        start_ms = int(display.get("from", 0))
        end_ms = int(display.get("to", duration * 1000))
        trim_from = int(trim.get("from", 0))
        trim_to = trim.get("to")
        if trim_to is not None:
            trim_to = int(trim_to)
        vol = safe_float(a["item"].get("details", {}).get("volume", 100)) / 100.0
        if vol <= 0:
            continue
        audio_sources.append({
            "index": idx,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "trim_from": trim_from,
            "trim_to": trim_to,
            "volume": vol,
        })

    audio_labels = []
    if audio_sources:
        for i, src in enumerate(audio_sources):
            display_dur_ms = max(0, src["end_ms"] - src["start_ms"])
            trim_len_ms = display_dur_ms
            if src["trim_to"] is not None:
                trim_len_ms = max(0, src["trim_to"] - src["trim_from"])
                trim_len_ms = min(trim_len_ms, display_dur_ms)
            duration_sec = max(0.0, trim_len_ms / 1000.0)
            if duration_sec <= 0:
                continue
            start_sec = max(0.0, src["trim_from"] / 1000.0)
            vol_filter = f",volume={src['volume']:.3f}" if src["volume"] != 1.0 else ""
            filter_parts.append(
                f"[{src['index']}:a]atrim=start={start_sec}:duration={duration_sec},asetpts=PTS-STARTPTS"
                f"{vol_filter},adelay={src['start_ms']}|{src['start_ms']},aresample=async=1:first_pts=0[aud{i}]"
            )
            audio_labels.append(f"[aud{i}]")

    if audio_labels:
        filter_parts.append(
            f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:normalize=0[outa]"
        )

    # -------------------------------------------------
    # 6️⃣ BUILD FFMPEG COMMAND
    # -------------------------------------------------
    print(f"   Visual inputs after validation: {len(visual_inputs)}")
    for i, v in enumerate(visual_inputs):
        print(f"     [{i}] {v['media_type'].upper()}: {v['src']}")
    print(f"   Audio inputs after validation: {len(audio_inputs)}")
    for i, a in enumerate(audio_inputs):
        print(f"     [{i}] AUDIO: {a['src']}")
    print("=" * 80 + "\n")
    
    cmd = ["ffmpeg", "-y"]

    for v in visual_inputs:
        if v["media_type"] == "image":
            cmd += ["-loop", "1", "-t", str(duration), "-i", v["src"]]
        else:
            cmd += ["-i", v["src"]]

    for a in audio_inputs:
        cmd += ["-i", a["src"]]

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", last_label
    ]

    if audio_labels:
        cmd += ["-map", "[outa]", "-c:a", "aac"]
    else:
        cmd += ["-an"]

    cmd += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-t", str(duration),
        output_path
    ]

    try:
        print("Render video FFmpeg command:", " ".join(shlex.quote(c) for c in cmd))
    except Exception:
        print("Render video FFmpeg command:", cmd)

    _run_with_resolved_exec(cmd, exec_name="ffmpeg", env_var="FFMPEG_BIN", check=True)
    return " ".join(shlex.quote(c) for c in cmd)

def render_video(task_id: str):
    task = db.video_tasks.find_one({"_id": ObjectId(task_id)})
    template = db.templates.find_one({"_id": ObjectId(task["template_id"])})
    customer = db.customers.find_one({"_id": ObjectId(task["customer_id"])})

    base_video = abs_media_path(template["base_video_url"])
    ensure_file_exists(base_video)

    text = customer["full_name"]

    folder = ensure_media_folder(
        template.get("folder_path") or template_folder_path(str(template.get("company_id")), str(template["_id"]))
    )
    output_path = get_media_abs_path(f"{folder}/{task_id}.mp4")

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
    _run_with_resolved_exec(cmd, exec_name="ffmpeg", env_var="FFMPEG_BIN", check=True)

    return output_path

def generate_ffmpeg_cmd(template):
    design = template['template_json']['design']
    track_map = design['trackItemsMap']
    duration = template.get('duration', 10)
    canvas_w, canvas_h = resolve_canvas_size(design)
    
    filter_parts = []
    input_files = []
    map_audio = []
    
    filter_parts.append(f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}[base];")
    last_label = "[base]"
    
    video_labels = []
    for idx, vid_id in enumerate([tid for tid in design['trackItemIds'] if track_map[tid]['type']=='video']):
        item = track_map[vid_id]
        path = item['details']['src']
        # ✅ Validate before using
        if not is_valid_src(path, label=f"video [{vid_id}]"):
            continue
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
        vstyle = build_visual_effect_filters_after_scale(item.get("details", {}))
        video_filter = build_visual_fit_filter(scaled_w, scaled_h, item.get("details", {}), vstyle, "video")
        filter_parts.append(f"[{idx}:v]{video_filter},setpts=PTS-STARTPTS[v{idx}];")
        filter_parts.append(f"{last_label}[v{idx}]overlay={left}:{top}:enable='between(t,{start},{end})'[o{idx}];")
        last_label = f"[o{idx}]"
        video_labels.append(last_label)
    
    image_items = [tid for tid in design['trackItemIds'] if track_map[tid]['type']=='image']
    for idx, img_id in enumerate(image_items):
        item = track_map[img_id]
        path = item['details']['src']
        # ✅ Validate before using
        if not is_valid_src(path, label=f"image [{img_id}]"):
            continue
        input_files.append(path)
        start = item['display']['from']/1000
        end = item['display']['to']/1000
        scale_x = parse_scale(item['details'].get('transform', 'scale(1)'))
        orig_w = float(item['details'].get('width', 0) or canvas_w)
        orig_h = float(item['details'].get('height', 0) or canvas_h)
        scaled_w = orig_w * scale_x
        scaled_h = orig_h * scale_x
        box_w = max(2, to_even(scaled_w))
        box_h = max(2, to_even(scaled_h))
        x, y = resolve_overlay_xy(item.get("details", {}), orig_w, orig_h, box_w, box_h, center_scaled=True)
        istyle = build_visual_effect_filters_after_scale(item.get("details", {}))
        image_filter = build_visual_fit_filter(box_w, box_h, item.get("details", {}), istyle, "image")
        filter_parts.append(f"[{len(video_labels)+idx}:v]{image_filter},setpts=PTS-STARTPTS[vimg{idx}];")
        filter_parts.append(f"{last_label}[vimg{idx}]overlay={x}:{y}:enable='between(t,{start},{end})'[oimg{idx}];")
        last_label = f"[oimg{idx}]"
    
    audio_items = [tid for tid in design['trackItemIds'] if track_map[tid]['type']=='audio']
    for idx, aud_id in enumerate(audio_items):
        item = track_map[aud_id]
        path = item['details']['src']
        # ✅ Validate before using
        if not is_valid_src(path, label=f"audio [{aud_id}]"):
            continue
        input_files.append(path)
        map_audio.append(f"-map {len(video_labels)+len(image_items)+idx}:a")
    
    filter_complex = "".join(filter_parts).rstrip(';')
    
    cmd = ["ffmpeg", "-y"]
    for f in input_files:
        cmd += ["-i", f]
    cmd += ["-filter_complex", filter_complex]
    cmd += map_audio
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(resolve_fps(design))]
    cmd += ["-t", str(duration), os.path.join(MEDIA_ROOT, f"output_preview_{uuid.uuid4().hex}.mp4")]
    
    return " ".join(shlex.quote(c) for c in cmd)
