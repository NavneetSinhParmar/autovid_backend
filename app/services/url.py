import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

def build_media_url(path: str | None) -> str | None:
    if not path:
        return None
    path = str(path).strip()
    if not path:
        return None
    if path.startswith(("http://", "https://", "data:", "blob:")):
        return path

    normalized = path.replace("\\", "/").strip()
    if normalized.startswith("./media/"):
        normalized = normalized[len("./media/"):]
    elif normalized.startswith("/media/"):
        normalized = normalized[len("/media/"):]
    elif normalized.startswith("media/"):
        normalized = normalized[len("media/"):]
    else:
        normalized = normalized.lstrip("/")

    return f"{BASE_URL.rstrip('/')}/media/{normalized}"
