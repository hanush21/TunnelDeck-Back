from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import AuditLog


class AuditService:
    def log_operation(
        self,
        db: Session,
        *,
        actor_email: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        success: bool,
        details: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        entry = AuditLog(
            actor_email=actor_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            success=success,
            details=details,
            error_message=error_message,
        )
        db.add(entry)
        db.flush()

    def list_entries(self, db: Session, *, limit: int = 100) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
        return list(db.scalars(stmt).all())
