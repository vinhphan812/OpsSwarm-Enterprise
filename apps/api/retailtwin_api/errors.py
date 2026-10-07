"""One JSON error envelope for every failed request."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def error_payload(code: str, message: str, details: list[dict[str, str]] | None = None) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message),
    )


def http_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload("http_error", message),
    )


def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    details: list[dict[str, str]] = []
    for item in exc.errors():
        loc = [str(part) for part in item.get("loc", []) if part != "body"]
        details.append(
            {
                "field": ".".join(loc) if loc else "body",
                "message": str(item.get("msg", "Invalid value")),
            }
        )
    return JSONResponse(
        status_code=422,
        content=error_payload("validation_error", "The request body is invalid.", details),
    )
