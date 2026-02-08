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
