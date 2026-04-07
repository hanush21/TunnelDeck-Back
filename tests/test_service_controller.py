import pytest

from app.infrastructure.tunnel.systemd import CloudflaredServiceController


def test_runtime_info_contains_expected_keys() -> None:
    controller = CloudflaredServiceController("cloudflared")
    info = controller.runtime_info()

    assert "platform_system" in info
    assert "os_name" in info
    assert "service_manager" in info


def test_manager_unavailable_status_and_restart_error() -> None:
    controller = CloudflaredServiceController("cloudflared")
    controller.manager = "none"

    assert controller.get_status() == "manager_unavailable"

    with pytest.raises(RuntimeError):
        controller.restart()
