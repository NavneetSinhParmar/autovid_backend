import json
import os
import subprocess
import math
from app.core.settings import settings

from app.core.settings import settings


def validate_generated_video(path: str) -> dict:
    result = subprocess.run(
        [
            os.getenv("FFPROBE_BIN", "ffprobe"), "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
            "-of", "json", path,
        ],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode != 0:
        raise ValueError("Generated video is invalid")
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if not video or video.get("codec_name") != "h264":
        raise ValueError("Generated video must use H.264")
    if int(video.get("width") or 0) > settings.max_output_width or int(video.get("height") or 0) > settings.max_output_height:
        raise ValueError("Generated video exceeds 720p")
    if audio and audio.get("codec_name") != "aac":
        raise ValueError("Generated video audio must use AAC")
    if not math.isfinite(duration) or duration <= 0 or duration > settings.max_output_video_seconds + 0.1:
        raise ValueError("Generated video duration exceeds configured limits or is invalid")
    return {
        "duration": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
    }
