from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id

        started_at = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - started_at) * 1000, 3)

        actor_email = getattr(request.state, "actor_email", None)
        client_ip = request.client.host if request.client else None

        logger.info(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "client_ip": client_ip,
                "actor_email": actor_email,
            }
        )

        response.headers["X-Request-ID"] = request_id
        return response
