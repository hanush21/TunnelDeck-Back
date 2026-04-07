from __future__ import annotations

import os
import platform
import shutil
import subprocess


class CloudflaredServiceController:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.platform_system = platform.system().lower()
        self.os_name = os.name
        self.manager = self._detect_manager()

    def _detect_manager(self) -> str:
        if self.platform_system == "linux" and shutil.which("systemctl"):
            return "systemd"
        if self.platform_system == "darwin" and shutil.which("launchctl"):
            return "launchctl"
        if self.platform_system == "windows" and shutil.which("sc"):
            return "sc"
        return "none"

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
        return "manager_unavailable"

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
