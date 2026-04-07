from fastapi import APIRouter

from app.api.routes import audit, auth, containers, dashboard, exposures, health, security

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(containers.router, prefix="/containers", tags=["containers"])
api_router.include_router(exposures.router, prefix="/exposures", tags=["exposures"])
api_router.include_router(security.router, prefix="/security", tags=["security"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
