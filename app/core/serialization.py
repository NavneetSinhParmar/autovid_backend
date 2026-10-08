from datetime import date, datetime
from enum import Enum
from typing import Any

from bson import ObjectId


def serialize_mongo(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [serialize_mongo(item) for item in value]
    if isinstance(value, tuple):
        return [serialize_mongo(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_mongo(item) for key, item in value.items()}
    return value


def serialize_document(document: dict, *, exclude: set[str] | None = None) -> dict:
    output = dict(document)
    if "_id" in output:
        output["id"] = str(output.pop("_id"))
    for key in exclude or set():
        output.pop(key, None)
    return serialize_mongo(output)
