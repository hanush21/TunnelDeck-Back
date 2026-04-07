from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes.audit import get_audit_service
from app.core.dependencies import (
    get_current_admin_user,
    get_db,
    get_security_service,
)
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
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    security_service: Annotated[SecurityService, Depends(get_security_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> TotpVerifyResponse:
    try:
        security_service.verify_user_totp(db, user.email, payload.code)
    except HTTPException as exc:
        _safe_log(
            db,
            audit_service,
            actor_email=user.email,
            action="security.verify_totp",
            success=False,
            details={"email": user.email},
            error_message=str(exc.detail),
        )
        raise

    _safe_log(
        db,
        audit_service,
        actor_email=user.email,
        action="security.verify_totp",
        success=True,
        details={"email": user.email},
    )
    return TotpVerifyResponse(valid=True)
