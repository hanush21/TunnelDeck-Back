from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user, get_db
from app.core.schemas import PaginationMeta
from app.modules.audit.schemas import AuditListResponse, AuditLogResponse
from app.modules.audit.service import AuditService
from app.modules.auth.schemas import AuthenticatedUser

router = APIRouter()


def get_audit_service() -> AuditService:
    return AuditService()


@router.get("", response_model=AuditListResponse)
def list_audit_entries(
    _: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditListResponse:
    total = audit_service.count_entries(db)
    entries = audit_service.list_entries(db, limit=limit, offset=offset)
    return AuditListResponse(
        meta=PaginationMeta(total=total, limit=limit, offset=offset),
        entries=[AuditLogResponse.model_validate(entry, from_attributes=True) for entry in entries],
    )
