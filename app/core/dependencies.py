from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.rate_limiter import InMemoryRateLimiter, rate_limiter
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


def get_rate_limiter() -> InMemoryRateLimiter:
    return rate_limiter


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _raise_rate_limit(scope: str, retry_after: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "rate_limit_exceeded",
            "message": "Too many TOTP attempts, try again later",
            "details": {
                "scope": scope,
            },
        },
        headers={"Retry-After": str(retry_after)},
    )


def apply_totp_rate_limit(
    request: Request,
    user_email: str,
    limiter: InMemoryRateLimiter,
    settings: Settings,
) -> None:
    client_ip = _get_client_ip(request)
    ip_key = f"totp:ip:{client_ip}"
    email_key = f"totp:email:{user_email.lower()}"

    allowed, retry_after = limiter.check_and_increment(
        ip_key,
        max_requests=settings.RATE_LIMIT_TOTP_IP_MAX,
        window_seconds=settings.RATE_LIMIT_TOTP_IP_WINDOW_SECONDS,
    )
    if not allowed:
        _raise_rate_limit("ip", retry_after)

    allowed, retry_after = limiter.check_and_increment(
        email_key,
        max_requests=settings.RATE_LIMIT_TOTP_EMAIL_MAX,
        window_seconds=settings.RATE_LIMIT_TOTP_EMAIL_WINDOW_SECONDS,
    )
    if not allowed:
        _raise_rate_limit("email", retry_after)


def get_current_admin_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    user = auth_service.verify_firebase_token(db, credentials.credentials)
    request.state.actor_email = user.email
    return user


def get_current_admin_with_totp(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    security_service: Annotated[SecurityService, Depends(get_security_service)],
    limiter: Annotated[InMemoryRateLimiter, Depends(get_rate_limiter)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> AuthenticatedUser:
    if not x_totp_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-TOTP-Code header",
        )

    apply_totp_rate_limit(request, user.email, limiter, settings)
    security_service.verify_user_totp(db, user.email, x_totp_code)
    return user
