from __future__ import annotations

import logging
import os
from typing import Any

import firebase_admin
from fastapi import HTTPException, status
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.infrastructure.persistence.models import User
from app.modules.auth.schemas import AuthenticatedUser

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _get_firebase_app(self) -> firebase_admin.App:
        if firebase_admin._apps:
            return firebase_admin.get_app()

        if self.settings.FIREBASE_CREDENTIALS_FILE:
            cred = credentials.Certificate(self.settings.FIREBASE_CREDENTIALS_FILE)
        else:
            cred = credentials.Certificate(
                {
                    "type": "service_account",
                    "project_id": self.settings.FIREBASE_PROJECT_ID,
                    "private_key": self.settings.firebase_private_key_multiline,
                    "client_email": self.settings.FIREBASE_CLIENT_EMAIL,
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )

        return firebase_admin.initialize_app(cred, {"projectId": self.settings.FIREBASE_PROJECT_ID})

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _upsert_user(self, db: Session, decoded_token: dict[str, Any], email: str) -> None:
        stmt = select(User).where(User.email == email)
        user = db.scalar(stmt)

        if user is None:
            user = User(
                email=email,
                firebase_uid=decoded_token.get("uid"),
                display_name=decoded_token.get("name"),
            )
            db.add(user)
        else:
            user.firebase_uid = decoded_token.get("uid")
            user.display_name = decoded_token.get("name")
            db.add(user)

        db.flush()

    def verify_firebase_token(self, db: Session, token: str) -> AuthenticatedUser:
        try:
            firebase_app = self._get_firebase_app()
            decoded_token = firebase_auth.verify_id_token(token, app=firebase_app)
        except Exception as exc:
            logger.error(
                "firebase_verify_failed",
                extra={
                    "exc_type": type(exc).__name__,
                    "exc_msg": str(exc),
                    "firebase_project_id": self.settings.FIREBASE_PROJECT_ID,
                    "firebase_client_email": self.settings.FIREBASE_CLIENT_EMAIL,
                    "firebase_credentials_file": self.settings.FIREBASE_CREDENTIALS_FILE or "(none - using env vars)",
                    "google_app_creds_env": os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "(not set)"),
                    "private_key_starts_with": (
                        self.settings.firebase_private_key_multiline[:40]
                        if self.settings.firebase_private_key_multiline
                        else "(empty)"
                    ),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Firebase token",
            ) from exc

        email = decoded_token.get("email")
        uid = decoded_token.get("uid")

        if not email or not uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firebase token missing required claims",
            )

        normalized_email = self._normalize_email(email)

        if normalized_email not in self.settings.allowed_admin_emails:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not in admin allowlist",
            )

        self._upsert_user(db, decoded_token, normalized_email)

        return AuthenticatedUser(
            uid=uid,
            email=normalized_email,
            name=decoded_token.get("name"),
        )
