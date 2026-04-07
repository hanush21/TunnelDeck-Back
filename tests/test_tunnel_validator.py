import pytest

from app.infrastructure.tunnel.validator import (
    TunnelValidationError,
    build_service_url,
    validate_ingress,
)


def test_validate_ingress_requires_fallback_last() -> None:
    ingress = [{"hostname": "app.example.com", "service": "http://localhost:3000"}]

    with pytest.raises(TunnelValidationError):
        validate_ingress(ingress)


def test_validate_ingress_rejects_duplicate_hostnames() -> None:
    ingress = [
        {"hostname": "app.example.com", "service": "http://localhost:3000"},
        {"hostname": "app.example.com", "service": "http://localhost:3001"},
        {"service": "http_status:404"},
    ]

    with pytest.raises(TunnelValidationError):
        validate_ingress(ingress)


def test_build_service_url_rejects_invalid_port() -> None:
    with pytest.raises(TunnelValidationError):
        build_service_url("http", "localhost", 70000)


def test_validate_ingress_accepts_valid_entries() -> None:
    ingress = [
        {"hostname": "app.example.com", "service": "http://localhost:3000"},
        {"hostname": "api.example.com", "service": "https://localhost:3443"},
        {"service": "http_status:404"},
    ]

    validate_ingress(ingress)
