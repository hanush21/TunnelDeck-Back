from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.persistence.database import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    docs_enabled = settings.APP_ENV != "production"

    app = FastAPI(
        title="TunnelDeck Backend",
        version="1.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-TOTP-Code"],
    )

    app.include_router(api_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    return app


app = create_app()
