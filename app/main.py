from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.hardening import run_startup_hardening_checks
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.infrastructure.persistence.database import get_db_session, init_db

logger = logging.getLogger("app.startup")


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

    app.add_middleware(RequestContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-TOTP-Code"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()
        run_startup_hardening_checks(settings)
        _import_config_entries_on_startup(settings)

    return app


def _import_config_entries_on_startup(settings) -> None:
    from app.modules.tunnel.service import TunnelService

    tunnel_service = TunnelService(settings)
    db = get_db_session()
    try:
        imported = tunnel_service.import_external_config_entries(
            db, actor_email="system@startup"
        )
        if imported:
            db.commit()
            logger.info(
                {
                    "event": "startup_config_import",
                    "imported_count": len(imported),
                    "hostnames": [e.hostname for e in imported],
                }
            )
    except Exception:
        logger.exception({"event": "startup_config_import_failed"})
        db.rollback()
    finally:
        db.close()


app = create_app()
