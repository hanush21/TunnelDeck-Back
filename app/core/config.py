from __future__ import annotations

from functools import lru_cache
from typing import Literal
import os

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
    CLOUDFLARED_CONTROL_MODE: Literal["auto", "systemd", "launchctl", "sc", "docker", "none"] = (
        "auto"
    )
    CLOUDFLARED_DOCKER_CONTAINER_NAME: str = "cloudflared"
    CLOUDFLARED_BACKUP_DIR: str = "./backups/cloudflared"
    CLOUDFLARED_BACKUP_MAX_FILES: int = 20
    TUNNEL_CONFIG_LOCK_PATH: str = "./backups/cloudflared/config.lock"
    TUNNEL_CONFIG_LOCK_TIMEOUT_SECONDS: int = 10

    DOCKER_SOCKET_PATH: str = "/var/run/docker.sock"

    CORS_ALLOWED_ORIGINS: str = ""

    RATE_LIMIT_TOTP_IP_MAX: int = 5
    RATE_LIMIT_TOTP_IP_WINDOW_SECONDS: int = 60
    RATE_LIMIT_TOTP_EMAIL_MAX: int = 10
    RATE_LIMIT_TOTP_EMAIL_WINDOW_SECONDS: int = 300

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

        if self.CLOUDFLARED_BACKUP_MAX_FILES < 1:
            raise ValueError("CLOUDFLARED_BACKUP_MAX_FILES must be >= 1")

        if self.TUNNEL_CONFIG_LOCK_TIMEOUT_SECONDS < 1:
            raise ValueError("TUNNEL_CONFIG_LOCK_TIMEOUT_SECONDS must be >= 1")

        if self.CLOUDFLARED_CONTROL_MODE == "docker":
            if not self.DOCKER_SOCKET_PATH:
                raise ValueError("DOCKER_SOCKET_PATH is required when CLOUDFLARED_CONTROL_MODE=docker")
            if not self.CLOUDFLARED_DOCKER_CONTAINER_NAME.strip():
                raise ValueError(
                    "CLOUDFLARED_DOCKER_CONTAINER_NAME is required when CLOUDFLARED_CONTROL_MODE=docker"
                )

        for value, name in [
            (self.RATE_LIMIT_TOTP_IP_MAX, "RATE_LIMIT_TOTP_IP_MAX"),
            (self.RATE_LIMIT_TOTP_IP_WINDOW_SECONDS, "RATE_LIMIT_TOTP_IP_WINDOW_SECONDS"),
            (self.RATE_LIMIT_TOTP_EMAIL_MAX, "RATE_LIMIT_TOTP_EMAIL_MAX"),
            (self.RATE_LIMIT_TOTP_EMAIL_WINDOW_SECONDS, "RATE_LIMIT_TOTP_EMAIL_WINDOW_SECONDS"),
        ]:
            if value < 1:
                raise ValueError(f"{name} must be >= 1")

        if self.APP_ENV == "production":
            for origin in self.cors_allowed_origins:
                low = origin.lower()
                if "localhost" in low or "127.0.0.1" in low:
                    raise ValueError("Localhost CORS origins are not allowed in production")

            if os.name != "nt" and not self.CLOUDFLARED_CONFIG_PATH.startswith("/"):
                raise ValueError("CLOUDFLARED_CONFIG_PATH must be absolute in production")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
