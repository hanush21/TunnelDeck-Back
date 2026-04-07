from __future__ import annotations

import re

import pyotp
from cryptography.fernet import Fernet
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.infrastructure.persistence.models import TotpSecret, User

TOTP_CODE_REGEX = re.compile(r"^\d{6}$")


class SecurityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fernet = Fernet(settings.TOTP_ENCRYPTION_KEY)

    def _encrypt_secret(self, secret: str) -> str:
        return self._fernet.encrypt(secret.encode("utf-8")).decode("utf-8")

    def _decrypt_secret(self, encrypted_secret: str) -> str:
        return self._fernet.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")

    def validate_totp_code_format(self, code: str) -> None:
        if not TOTP_CODE_REGEX.match(code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="TOTP code must be 6 digits",
            )

    def _get_user_secret(self, db: Session, email: str) -> str:
        stmt = (
            select(TotpSecret)
            .join(User, TotpSecret.user_id == User.id)
            .where(User.email == email)
        )
        totp_secret_row = db.scalar(stmt)

        if totp_secret_row is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No TOTP secret configured for admin",
            )

        return self._decrypt_secret(totp_secret_row.encrypted_secret)

    def verify_user_totp(self, db: Session, email: str, code: str) -> None:
        self.validate_totp_code_format(code)

        secret = self._get_user_secret(db, email)
        totp = pyotp.TOTP(secret)

        if not totp.verify(code, valid_window=1):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid TOTP code",
            )

    def set_user_totp_secret(
        self,
        db: Session,
        *,
        email: str,
        secret: str,
        firebase_uid: str | None = None,
        display_name: str | None = None,
    ) -> None:
        normalized_email = email.strip().lower()

        try:
            pyotp.TOTP(secret).now()
        except Exception as exc:
            raise ValueError("Invalid TOTP secret format") from exc

        user_stmt = select(User).where(User.email == normalized_email)
        user = db.scalar(user_stmt)
        if user is None:
            user = User(
                email=normalized_email,
                firebase_uid=firebase_uid,
                display_name=display_name,
            )
            db.add(user)
            db.flush()

        secret_stmt = select(TotpSecret).where(TotpSecret.user_id == user.id)
        secret_row = db.scalar(secret_stmt)
        encrypted_secret = self._encrypt_secret(secret)

        if secret_row is None:
            secret_row = TotpSecret(user_id=user.id, encrypted_secret=encrypted_secret)
            db.add(secret_row)
        else:
            secret_row.encrypted_secret = encrypted_secret
            db.add(secret_row)

        db.flush()
