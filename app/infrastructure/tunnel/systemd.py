from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from docker.errors import DockerException, NotFound

from app.infrastructure.docker.client import create_docker_client


class CloudflaredServiceController:
    def __init__(
        self,
        service_name: str,
        *,
        control_mode: str = "auto",
        docker_socket_path: str = "/var/run/docker.sock",
        docker_container_name: str | None = None,
    ) -> None:
        self.service_name = service_name
        self.control_mode = (control_mode or "auto").strip().lower()
        self.docker_socket_path = docker_socket_path
        self.docker_container_name = (docker_container_name or service_name).strip() or service_name
        self.platform_system = platform.system().lower()
        self.os_name = os.name
        self.manager = self._detect_manager()

    def _detect_manager(self) -> str:
        if self.control_mode in {"systemd", "launchctl", "sc", "docker", "none"}:
            return self.control_mode
        if self.platform_system == "linux" and shutil.which("systemctl"):
            return "systemd"
        if self.platform_system == "darwin" and shutil.which("launchctl"):
            return "launchctl"
        if self.platform_system == "windows" and shutil.which("sc"):
            return "sc"
        if self._docker_socket_exists():
            return "docker"
        return "none"

    def _docker_socket_exists(self) -> bool:
        if not self.docker_socket_path:
            return False
        # For Windows named pipe URLs such as npipe:////./pipe/docker_engine.
        if self.docker_socket_path.startswith("npipe://"):
            return True
        return Path(self.docker_socket_path).exists()

    def _docker_status_to_health(self, docker_status: str) -> str:
        if docker_status == "running":
            return "active"
        if docker_status in {"created", "paused", "restarting", "removing", "exited", "dead"}:
            return "inactive"
        return "unknown"

    def _get_docker_container_status(self) -> str:
        client = create_docker_client(self.docker_socket_path)
        try:
            container = client.containers.get(self.docker_container_name)
            container.reload()
            state = container.attrs.get("State") or {}
            return str(state.get("Status", "unknown")).lower()
        except NotFound:
            return "not_found"
        except DockerException as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            client.close()

    def _restart_docker_container(self) -> None:
        client = create_docker_client(self.docker_socket_path)
        try:
            container = client.containers.get(self.docker_container_name)
            container.restart(timeout=15)
            container.reload()
            state = container.attrs.get("State") or {}
            if str(state.get("Status", "")).lower() != "running":
                raise RuntimeError(
                    f"container '{self.docker_container_name}' is not running after restart"
                )
        except NotFound as exc:
            raise RuntimeError(
                f"container '{self.docker_container_name}' not found"
            ) from exc
        except DockerException as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            client.close()

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

    def runtime_info(self) -> dict[str, str]:
        return {
            "platform_system": self.platform_system,
            "os_name": self.os_name,
            "service_manager": self.manager,
            "control_mode": self.control_mode,
            "docker_container_name": self.docker_container_name,
        }

    def restart(self) -> None:
        if self.manager == "systemd":
            self._restart_systemd()
            return
        if self.manager == "launchctl":
            self._restart_launchctl()
            return
        if self.manager == "sc":
            self._restart_sc()
            return
        if self.manager == "docker":
            self._restart_docker_container()
            return
        raise RuntimeError("no supported service manager found on this host")

    def _restart_systemd(self) -> None:
        result = self._run(["systemctl", "restart", self.service_name])
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "failed to restart service"
            raise RuntimeError(message)

    def _restart_launchctl(self) -> None:
        # Try system service first, then current GUI user service.
        candidates = [f"system/{self.service_name}"]
        if hasattr(os, "getuid"):
            candidates.append(f"gui/{os.getuid()}/{self.service_name}")

        errors: list[str] = []
        for target in candidates:
            result = self._run(["launchctl", "kickstart", "-k", target])
            if result.returncode == 0:
                return
            err = result.stderr.strip() or result.stdout.strip() or f"failed: {target}"
            errors.append(f"{target}: {err}")

        raise RuntimeError("; ".join(errors))

    def _restart_sc(self) -> None:
        stop_result = self._run(["sc", "stop", self.service_name])
        if stop_result.returncode not in (0, 1062):  # already stopped
            message = stop_result.stderr.strip() or stop_result.stdout.strip() or "failed to stop service"
            raise RuntimeError(message)

        start_result = self._run(["sc", "start", self.service_name])
        if start_result.returncode != 0:
            message = start_result.stderr.strip() or start_result.stdout.strip() or "failed to start service"
            raise RuntimeError(message)

    def get_status(self) -> str:
        if self.manager == "systemd":
            result = self._run(["systemctl", "is-active", self.service_name])
            return (result.stdout or "unknown").strip()
        if self.manager == "launchctl":
            return self._status_launchctl()
        if self.manager == "sc":
            return self._status_sc()
        if self.manager == "docker":
            return self._status_docker()
        return "manager_unavailable"

    def _status_docker(self) -> str:
        try:
            status = self._get_docker_container_status()
        except Exception:
            return "status_check_error"
        if status == "not_found":
            return "not_found"
        return self._docker_status_to_health(status)

    def _status_launchctl(self) -> str:
        result = self._run(["launchctl", "list"])
        if result.returncode != 0:
            return "status_check_error"

        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2] == self.service_name:
                pid = parts[0]
                return "active" if pid.isdigit() and int(pid) > 0 else "inactive"
        return "not_found"

    def _status_sc(self) -> str:
        result = self._run(["sc", "query", self.service_name])
        if result.returncode != 0:
            return "not_found"

        output = (result.stdout or "").upper()
        if "STATE" in output and "RUNNING" in output:
            return "active"
        if "STATE" in output and "STOPPED" in output:
            return "inactive"
        return "unknown"

    def is_active(self) -> bool:
        return self.get_status() == "active"


# Backward-compatible alias used by existing imports.
CloudflaredSystemdController = CloudflaredServiceController
