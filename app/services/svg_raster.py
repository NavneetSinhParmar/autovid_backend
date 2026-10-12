"""Rasterize self-contained SVG logos; external/file/data URLs are forbidden."""
import math
import re

from app.core.errors import AppError


def svg_to_png(content):
    try:
        from defusedxml import ElementTree
    except (ImportError, OSError) as exc:
        raise AppError(503, "SVG_CONVERTER_UNAVAILABLE", "CairoSVG or its native Cairo dependency is unavailable") from exc
    try:
        root = ElementTree.fromstring(content)
        if root.tag != "{http://www.w3.org/2000/svg}svg":
            raise ValueError("Expected SVG root")
        # Preflight all references; CSS url()/imports are disallowed, including data.
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] in {"script", "foreignObject"}:
                raise ValueError("Active content is not supported")
            for key, value in element.attrib.items():
                if key.rsplit("}", 1)[-1] in {"href", "src"} and value and not value.startswith("#"):
                    raise ValueError("External references are not supported")
            text = " ".join(element.attrib.values()) + " " + (element.text or "")
            if re.search(r"@import", text, re.I):
                raise ValueError("CSS imports are not supported")
            for reference in re.findall(r"url\s*\((.*?)\)", text, re.I | re.S):
                if not reference.strip().strip("\"'").startswith("#"):
                    raise ValueError("External CSS resources are not supported")
        viewbox = re.split(r"[\s,]+", root.get("viewBox", "").strip())
        if len(viewbox) == 4:
            width, height = float(viewbox[2]), float(viewbox[3])
        else:
            width = float(root.get("width", "").removesuffix("px"))
            height = float(root.get("height", "").removesuffix("px"))
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            raise ValueError("SVG needs positive dimensions or a viewBox")
        scale = min(1, 2048 / width, 2048 / height)

        def deny_fetch(*args, **kwargs):
            raise ValueError("External resources are not supported")

        try:
            from cairosvg.surface import PNGSurface
        except (ImportError, OSError) as exc:
            raise AppError(503, "SVG_CONVERTER_UNAVAILABLE", "CairoSVG or its native Cairo dependency is unavailable") from exc

        return PNGSurface.convert(
            bytestring=content, unsafe=False, url_fetcher=deny_fetch,
            output_width=max(1, int(width * scale)), output_height=max(1, int(height * scale)),
        )
    except AppError:
        raise
    except Exception as exc:
        raise AppError(400, "INVALID_MEDIA_TYPE", "Invalid or unsupported SVG; use a self-contained SVG with dimensions") from exc
