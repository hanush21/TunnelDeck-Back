from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.infrastructure.persistence.database import get_db_session
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.auth.service import AuthService
from app.modules.security.service import SecurityService

bearer_scheme = HTTPBearer(auto_error=False)


def get_settings_dependency() -> Settings:
    return get_settings()


def get_db() -> Session:
    db = get_db_session()
    try:
        yield db
    finally:
        db.close()


def get_auth_service(
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> AuthService:
    return AuthService(settings)


def get_security_service(
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> SecurityService:
    return SecurityService(settings)


def get_current_admin_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    return auth_service.verify_firebase_token(db, credentials.credentials)


def get_current_admin_with_totp(
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    security_service: Annotated[SecurityService, Depends(get_security_service)],
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> AuthenticatedUser:
    if not x_totp_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-TOTP-Code header",
        )

    security_service.verify_user_totp(db, user.email, x_totp_code)
    return user
