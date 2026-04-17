from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import containers as containers_routes
from app.api.routes import health as health_routes
from app.core.config import get_settings
from app.core.dependencies import (
    get_auth_service,
    get_db,
    get_rate_limiter,
    get_security_service,
    get_settings_dependency,
)
from app.core.rate_limiter import InMemoryRateLimiter
from app.infrastructure.persistence.models import AuditLog, Base, Exposure, ServiceType
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.docker.schemas import ContainerSummaryResponse


class FakeAuthService:
    def verify_firebase_token(self, db: Session, token: str) -> AuthenticatedUser:
        if token == "deny":
            raise HTTPException(status_code=403, detail="User is not in admin allowlist")
        return AuthenticatedUser(uid="uid-1", email="admin@example.com", name="Admin")


class FakeSecurityService:
    def verify_user_totp(self, db: Session, email: str, code: str) -> None:
        return None


class FakeDockerService:
    def __init__(self) -> None:
        self.fail_list = False

    def list_containers(self) -> list[ContainerSummaryResponse]:
        if self.fail_list:
            raise HTTPException(status_code=503, detail="Docker daemon unavailable")

        now = datetime.now(timezone.utc)
        return [
            ContainerSummaryResponse(
                id="c-1",
                name="alpha",
                image="img:v1",
                state="running",
                status="running",
                published_ports=[],
                labels={},
                networks=["bridge"],
                created_at=now,
                started_at=now,
            ),
            ContainerSummaryResponse(
                id="c-2",
                name="beta",
                image="img:v1",
                state="running",
                status="running",
                published_ports=[],
                labels={},
                networks=["bridge"],
                created_at=now,
                started_at=now,
            ),
            ContainerSummaryResponse(
                id="c-3",
                name="gamma",
                image="img:v1",
                state="exited",
                status="exited",
                published_ports=[],
                labels={},
                networks=["bridge"],
                created_at=now,
                started_at=now,
            ),
        ]

    def get_container(self, container_id: str) -> ContainerSummaryResponse:
        return self.list_containers()[0]

    def ensure_container_exists(self, container_name: str) -> None:
        return None


class FakeTunnelService:
    def __init__(self) -> None:
        self.fail_apply = False
        self.fail_restart = False

    def get_health(self) -> dict:
        return {
            "service_name": "cloudflared",
            "status": "active",
            "is_active": True,
            "config_exists": True,
            "platform_system": "linux",
            "os_name": "posix",
            "service_manager": "systemd",
        }

    def import_external_config_entries(
        self,
        db: Session,
        *,
        actor_email: str,
    ) -> list:
        return []

    def apply_exposure_config(
        self,
        db: Session,
        *,
        exposures: list[Exposure],
        actor_email: str,
        reason: str,
    ) -> None:
        if self.fail_apply:
            raise HTTPException(
                status_code=500,
                detail={"code": "tunnel_apply_failed", "message": "Failed applying tunnel config"},
            )
        return None

    def restart_cloudflared(self) -> dict:
        if self.fail_restart:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "cloudflared_restart_failed",
                    "message": "Failed to restart cloudflared service",
                },
            )
        return self.get_health()


@pytest.fixture
def client_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "integration.db"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ALLOWED_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIREBASE_CLIENT_EMAIL", "svc@test-project.iam.gserviceaccount.com")
    monkeypatch.setenv("FIREBASE_PRIVATE_KEY", "dummy")

    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()

    engine = create_engine(f"sqlite:///{tmp_path / 'api_test.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    fake_docker = FakeDockerService()
    fake_tunnel = FakeTunnelService()
    limiter = InMemoryRateLimiter()

    settings = get_settings().model_copy(deep=True)
    settings.RATE_LIMIT_TOTP_IP_MAX = 1
    settings.RATE_LIMIT_TOTP_IP_WINDOW_SECONDS = 60
    settings.RATE_LIMIT_TOTP_EMAIL_MAX = 2
    settings.RATE_LIMIT_TOTP_EMAIL_WINDOW_SECONDS = 300

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    app.dependency_overrides[get_security_service] = lambda: FakeSecurityService()
    app.dependency_overrides[get_settings_dependency] = lambda: settings
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[containers_routes.get_docker_service] = lambda: fake_docker
    app.dependency_overrides[health_routes.get_tunnel_service] = lambda: fake_tunnel

    with TestClient(app) as client:
        yield {
            "client": client,
            "session_factory": TestingSessionLocal,
            "fake_docker": fake_docker,
            "fake_tunnel": fake_tunnel,
        }

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _auth_headers(token: str = "ok") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_error_envelope_for_missing_token(client_bundle) -> None:
    client: TestClient = client_bundle["client"]

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["request_id"]
    assert response.headers.get("X-Request-ID")


def test_auth_deny_returns_wrapped_error(client_bundle) -> None:
    client: TestClient = client_bundle["client"]

    response = client.get("/api/v1/auth/me", headers=_auth_headers("deny"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_totp_required_on_mutation(client_bundle) -> None:
    client: TestClient = client_bundle["client"]

    payload = {
        "container_name": "alpha",
        "hostname": "app.example.com",
        "service_type": "http",
        "target_host": "localhost",
        "target_port": 3000,
        "enabled": True,
    }
    response = client.post("/api/v1/exposures", json=payload, headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Missing X-TOTP-Code header"


def test_restart_cloudflared_requires_totp(client_bundle) -> None:
    client: TestClient = client_bundle["client"]

    response = client.post("/api/v1/health/cloudflared/restart", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Missing X-TOTP-Code header"


def test_verify_totp_rate_limited(client_bundle) -> None:
    client: TestClient = client_bundle["client"]

    first = client.post(
        "/api/v1/security/verify-totp",
        json={"code": "123456"},
        headers=_auth_headers(),
    )
    second = client.post(
        "/api/v1/security/verify-totp",
        json={"code": "123456"},
        headers=_auth_headers(),
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limit_exceeded"
    assert second.headers.get("Retry-After") is not None


def test_pagination_meta_for_exposures_and_audit(client_bundle) -> None:
    client: TestClient = client_bundle["client"]
    SessionLocal = client_bundle["session_factory"]

    db = SessionLocal()
    try:
        db.add_all(
            [
                Exposure(
                    container_name="alpha",
                    hostname="alpha.example.com",
                    service_type=ServiceType.HTTP,
                    target_host="localhost",
                    target_port=3000,
                    enabled=True,
                    created_by="admin@example.com",
                ),
                Exposure(
                    container_name="beta",
                    hostname="beta.example.com",
                    service_type=ServiceType.HTTP,
                    target_host="localhost",
                    target_port=3001,
                    enabled=True,
                    created_by="admin@example.com",
                ),
                Exposure(
                    container_name="gamma",
                    hostname="gamma.example.com",
                    service_type=ServiceType.HTTP,
                    target_host="localhost",
                    target_port=3002,
                    enabled=True,
                    created_by="admin@example.com",
                ),
            ]
        )

        db.add_all(
            [
                AuditLog(
                    actor_email="admin@example.com",
                    action="x",
                    resource_type="exposure",
                    success=True,
                ),
                AuditLog(
                    actor_email="admin@example.com",
                    action="y",
                    resource_type="exposure",
                    success=True,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    exposures_response = client.get(
        "/api/v1/exposures?limit=2&offset=1",
        headers=_auth_headers(),
    )
    assert exposures_response.status_code == 200
    exposures_body = exposures_response.json()
    assert exposures_body["meta"] == {"total": 3, "limit": 2, "offset": 1}
    assert len(exposures_body["items"]) == 2

    audit_response = client.get(
        "/api/v1/audit?limit=1&offset=1",
        headers=_auth_headers(),
    )
    assert audit_response.status_code == 200
    audit_body = audit_response.json()
    assert audit_body["meta"] == {"total": 2, "limit": 1, "offset": 1}
    assert len(audit_body["entries"]) == 1


def test_containers_pagination(client_bundle) -> None:
    client: TestClient = client_bundle["client"]

    response = client.get("/api/v1/containers?limit=2&offset=1", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"total": 3, "limit": 2, "offset": 1}
    assert len(body["items"]) == 2


def test_readiness_degraded_when_docker_unavailable(client_bundle) -> None:
    client: TestClient = client_bundle["client"]
    fake_docker: FakeDockerService = client_bundle["fake_docker"]
    fake_docker.fail_list = True

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["components"]["docker"]["ready"] is False


def test_exposure_create_tunnel_failure_wrapped_error(client_bundle) -> None:
    client: TestClient = client_bundle["client"]
    fake_tunnel: FakeTunnelService = client_bundle["fake_tunnel"]
    fake_tunnel.fail_apply = True

    payload = {
        "container_name": "alpha",
        "hostname": "zeta.example.com",
        "service_type": "http",
        "target_host": "localhost",
        "target_port": 3010,
        "enabled": True,
    }
    response = client.post(
        "/api/v1/exposures",
        json=payload,
        headers={**_auth_headers(), "X-TOTP-Code": "123456"},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "tunnel_apply_failed"


def test_restart_cloudflared_success_creates_audit_log(client_bundle) -> None:
    client: TestClient = client_bundle["client"]
    SessionLocal = client_bundle["session_factory"]

    response = client.post(
        "/api/v1/health/cloudflared/restart",
        headers={**_auth_headers(), "X-TOTP-Code": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"

    db = SessionLocal()
    try:
        log = db.query(AuditLog).filter(AuditLog.action == "cloudflared.restart").first()
        assert log is not None
        assert log.success is True
    finally:
        db.close()


def test_validation_error_is_wrapped(client_bundle) -> None:
    client: TestClient = client_bundle["client"]

    response = client.post(
        "/api/v1/security/verify-totp",
        json={"code": "12"},
        headers=_auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
