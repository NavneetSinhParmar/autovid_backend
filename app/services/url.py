import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

def build_media_url(path: str | None) -> str | None:
    if not path:
        return None
    return f"{BASE_URL}/media/{path}"
