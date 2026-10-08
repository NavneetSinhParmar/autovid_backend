from typing import Any

from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        payload = {"code": code, "message": message}
        if details is not None:
            payload["details"] = details
        super().__init__(status_code=status_code, detail=payload)
