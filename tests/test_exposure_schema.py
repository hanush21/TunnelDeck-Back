import pytest
from pydantic import ValidationError

from app.modules.exposures.schemas import ExposureCreateRequest


def test_invalid_hostname_fails() -> None:
    with pytest.raises(ValidationError):
        ExposureCreateRequest(
            container_name="my-app",
            hostname="invalid_hostname",
            service_type="http",
            target_host="localhost",
            target_port=3000,
            enabled=True,
        )


def test_invalid_target_host_with_scheme_fails() -> None:
    with pytest.raises(ValidationError):
        ExposureCreateRequest(
            container_name="my-app",
            hostname="app.example.com",
            service_type="http",
            target_host="http://localhost",
            target_port=3000,
            enabled=True,
        )


def test_valid_exposure_payload() -> None:
    payload = ExposureCreateRequest(
        container_name="my-app",
        hostname="app.example.com",
        service_type="https",
        target_host="localhost",
        target_port=3443,
        enabled=True,
    )

    assert payload.hostname == "app.example.com"
    assert payload.service_type == "https"
