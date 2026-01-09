from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiError(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ApiResponse[T](BaseModel):
    ok: bool
    data: T | None = None
    error: ApiError | None = None


def ok[T](data: T) -> ApiResponse[T]:
    return ApiResponse(ok=True, data=data)


def fail(*, code: str, message: str, details: Any | None = None) -> ApiResponse[None]:
    return ApiResponse(ok=False, error=ApiError(code=code, message=message, details=details))
