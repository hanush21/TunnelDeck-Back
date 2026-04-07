import pytest
from docker.errors import NotFound

from app.infrastructure.tunnel.systemd import CloudflaredServiceController


class _FakeContainer:
    def __init__(self, status: str = "running") -> None:
        self._status = status
        self.attrs = {"State": {"Status": self._status}}

    def reload(self) -> None:
        self.attrs = {"State": {"Status": self._status}}

    def restart(self, timeout: int = 15) -> None:
        self._status = "running"
        self.reload()


class _FakeContainers:
    def __init__(self, container: _FakeContainer | None) -> None:
        self._container = container

    def get(self, _: str) -> _FakeContainer:
        if self._container is None:
            raise NotFound("not found")
        return self._container


class _FakeDockerClient:
    def __init__(self, container: _FakeContainer | None) -> None:
        self.containers = _FakeContainers(container)

    def close(self) -> None:
        return None


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


def test_docker_mode_status_and_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    container = _FakeContainer(status="running")
    monkeypatch.setattr(
        "app.infrastructure.tunnel.systemd.create_docker_client",
        lambda _: _FakeDockerClient(container),
    )

    controller = CloudflaredServiceController(
        "cloudflared",
        control_mode="docker",
        docker_socket_path="/var/run/docker.sock",
        docker_container_name="cloudflared",
    )

    assert controller.get_status() == "active"
    assert controller.is_active() is True

    controller.restart()
    assert controller.get_status() == "active"


def test_docker_mode_not_found() -> None:
    controller = CloudflaredServiceController(
        "cloudflared",
        control_mode="docker",
    )
    controller._get_docker_container_status = lambda: "not_found"  # type: ignore[method-assign]

    assert controller.get_status() == "not_found"
