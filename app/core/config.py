from __future__ import annotations

from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: Literal["development", "production", "test"] = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    DATABASE_URL: str = "sqlite:///./tunneldeck.db"

    ALLOWED_ADMIN_EMAILS: str = Field(default="")

    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_CLIENT_EMAIL: str = ""
    FIREBASE_PRIVATE_KEY: str = ""
    FIREBASE_CREDENTIALS_FILE: str = ""

    TOTP_ENCRYPTION_KEY: str = ""

    CLOUDFLARED_CONFIG_PATH: str = "/etc/cloudflared/config.yml"
    CLOUDFLARED_SERVICE_NAME: str = "cloudflared"
    CLOUDFLARED_BACKUP_DIR: str = "./backups/cloudflared"

    DOCKER_SOCKET_PATH: str = "/var/run/docker.sock"

    CORS_ALLOWED_ORIGINS: str = ""

    @property
    def allowed_admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.ALLOWED_ADMIN_EMAILS.split(",")
            if email.strip()
        }

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.CORS_ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def firebase_private_key_multiline(self) -> str:
        return self.FIREBASE_PRIVATE_KEY.replace("\\n", "\n")

    @model_validator(mode="after")
    def validate_security_requirements(self) -> "Settings":
        if not self.allowed_admin_emails:
            raise ValueError("ALLOWED_ADMIN_EMAILS must include at least one admin email")

        if not self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must include at least one origin")

        if "*" in self.cors_allowed_origins:
            raise ValueError("Wildcard CORS origin is not allowed")

        if not self.TOTP_ENCRYPTION_KEY:
            raise ValueError("TOTP_ENCRYPTION_KEY is required")

        try:
            Fernet(self.TOTP_ENCRYPTION_KEY)
        except Exception as exc:
            raise ValueError("TOTP_ENCRYPTION_KEY is invalid Fernet key") from exc

        has_credentials_file = bool(self.FIREBASE_CREDENTIALS_FILE)
        has_env_credentials = all(
            [self.FIREBASE_PROJECT_ID, self.FIREBASE_CLIENT_EMAIL, self.FIREBASE_PRIVATE_KEY]
        )

        if not has_credentials_file and not has_env_credentials:
            raise ValueError(
                "Firebase credentials missing: set FIREBASE_CREDENTIALS_FILE or FIREBASE_* env vars"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
