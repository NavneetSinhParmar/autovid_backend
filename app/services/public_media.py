from urllib.parse import urlsplit, unquote


def media_reference_path(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if value.startswith(("http://", "https://")):
        value = urlsplit(value).path
    value = unquote(value).lstrip("./")
    for prefix in ("api/backend/media/", "api/backend-media/media/", "media/"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def references_media(value, path: str) -> bool:
    if isinstance(value, str):
        return media_reference_path(value) == path
    if isinstance(value, dict):
        return any(references_media(item, path) for item in value.values())
    if isinstance(value, list):
        return any(references_media(item, path) for item in value)
    return False
