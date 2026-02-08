import os
import re

# -------------------------------------------------
# BACKGROUND (image / video)
# -------------------------------------------------

def find_background(template_json: dict) -> dict | None:
    """
    Returns background item (image/video) if exists
    """
    design = template_json.get("design", {})
    track_items = design.get("trackItemsMap", {})

    for item in track_items.values():
        if item.get("type") in ("image", "video"):
            details = item.get("details", {})
            if details.get("isBackground") is True:
                return item

    return None


# -------------------------------------------------
# IMAGE ITEMS (excluding background)
# -------------------------------------------------

def get_image_items(template_json: dict) -> list:
    """
    Returns all image items except background
    """
    design = template_json.get("design", {})
    track_items = design.get("trackItemsMap", {})

    images = []
    for item in track_items.values():
        if item.get("type") == "image":
            details = item.get("details", {})
            if not details.get("isBackground"):
                images.append(item)

    return images


# -------------------------------------------------
# TEXT ITEMS
# -------------------------------------------------

def get_text_items(template_json: dict) -> list:
    """
    Returns all text items
    """
    design = template_json.get("design", {})
    track_items = design.get("trackItemsMap", {})

    return [
        item for item in track_items.values()
        if item.get("type") == "text"
    ]


# -------------------------------------------------
# PLACEHOLDER REPLACEMENT (nested safe)
# -------------------------------------------------

PLACEHOLDER_PATTERN = re.compile(r"\{\{([^}]+)\}\}")

def replace_placeholders(text: str, context: dict) -> str:
    """
    Replaces placeholders like:
    {{customer.full_name}}
    {{company.company_name}}

    Safe for FFmpeg drawtext
    """

    if not isinstance(text, str):
        return ""

    def resolve(match):
        path = match.group(1).strip().split(".")
        value = context

        for key in path:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return ""   # missing key → blank

        return str(value)

    return PLACEHOLDER_PATTERN.sub(resolve, text)
