from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings

logger = logging.getLogger("app.errors")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _code_for_status(status_code: int) -> str:
    mapping = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        423: "resource_locked",
        429: "rate_limited",
        500: "internal_error",
        503: "service_unavailable",
    }
    return mapping.get(status_code, "request_error")


def _default_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except Exception:
        return "Request error"


def _http_exception_payload(exc: HTTPException, request_id: str) -> dict[str, Any]:
    status_code = exc.status_code
    detail = exc.detail

    if isinstance(detail, dict):
        code = str(detail.get("code") or _code_for_status(status_code))
        message = str(detail.get("message") or _default_message(status_code))
        details = detail.get("details")
    elif isinstance(detail, str):
        code = _code_for_status(status_code)
        message = detail
        details = None
    else:
        code = _code_for_status(status_code)
        message = _default_message(status_code)
        details = detail

    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = _request_id(request)
        payload = _http_exception_payload(exc, request_id)
        headers = dict(exc.headers or {})
        headers["X-Request-ID"] = request_id
        return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = _request_id(request)
        payload = {
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
                "request_id": request_id,
            }
        }
        return JSONResponse(
            status_code=422,
            content=payload,
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        settings = get_settings()

        logger.exception(
            {
                "event": "unhandled_exception",
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "error": str(exc),
            }
        )

        details = None if settings.APP_ENV == "production" else str(exc)
        payload = {
            "error": {
                "code": "internal_error",
                "message": "Internal server error",
                "details": details,
                "request_id": request_id,
            }
        }
        return JSONResponse(
            status_code=500,
            content=payload,
            headers={"X-Request-ID": request_id},
        )
