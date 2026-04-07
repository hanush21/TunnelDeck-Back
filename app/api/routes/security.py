from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.routes.audit import get_audit_service
from app.core.dependencies import (
    apply_totp_rate_limit,
    get_current_admin_user,
    get_db,
    get_rate_limiter,
    get_security_service,
    get_settings_dependency,
)
from app.core.rate_limiter import InMemoryRateLimiter
from app.core.config import Settings
from app.modules.audit.service import AuditService
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.security.schemas import TotpVerifyRequest, TotpVerifyResponse
from app.modules.security.service import SecurityService

router = APIRouter()


def _safe_log(
    db: Session,
    audit_service: AuditService,
    *,
    actor_email: str,
    action: str,
    success: bool,
    details: dict | None = None,
    error_message: str | None = None,
) -> None:
    try:
        audit_service.log_operation(
            db,
            actor_email=actor_email,
            action=action,
            resource_type="security",
            success=success,
            details=details,
            error_message=error_message,
        )
        db.commit()
    except Exception:
        db.rollback()


@router.post("/verify-totp", response_model=TotpVerifyResponse)
def verify_totp(
    payload: TotpVerifyRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    security_service: Annotated[SecurityService, Depends(get_security_service)],
    limiter: Annotated[InMemoryRateLimiter, Depends(get_rate_limiter)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> TotpVerifyResponse:
    try:
        apply_totp_rate_limit(request, user.email, limiter, settings)
        security_service.verify_user_totp(db, user.email, payload.code)
    except HTTPException as exc:
        _safe_log(
            db,
            audit_service,
            actor_email=user.email,
            action="security.verify_totp",
            success=False,
            details={
                "email": user.email,
                "request_id": getattr(request.state, "request_id", None),
            },
            error_message=str(exc.detail),
        )
        raise

    _safe_log(
        db,
        audit_service,
        actor_email=user.email,
        action="security.verify_totp",
        success=True,
        details={
            "email": user.email,
            "request_id": getattr(request.state, "request_id", None),
        },
    )
    return TotpVerifyResponse(valid=True)
