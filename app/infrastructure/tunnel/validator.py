from __future__ import annotations

import re
from urllib.parse import urlparse

HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])(?:\.(?!-)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9]))+$"
)


class TunnelValidationError(ValueError):
    pass


def validate_hostname(hostname: str) -> None:
    if not HOSTNAME_PATTERN.match(hostname):
        raise TunnelValidationError("Invalid hostname format")


def build_service_url(service_type: str, target_host: str, target_port: int) -> str:
    if service_type not in {"http", "https"}:
        raise TunnelValidationError("service_type must be http or https")

    if target_port < 1 or target_port > 65535:
        raise TunnelValidationError("target_port must be between 1 and 65535")

    service_url = f"{service_type}://{target_host}:{target_port}"
    validate_service_url(service_url)
    return service_url


def validate_service_url(service_url: str) -> None:
    parsed = urlparse(service_url)

    if parsed.scheme not in {"http", "https"}:
        raise TunnelValidationError("Service URL must use http or https")

    if not parsed.hostname:
        raise TunnelValidationError("Service URL missing hostname")

    if parsed.port is None:
        raise TunnelValidationError("Service URL missing port")


def validate_ingress(ingress: list[dict]) -> None:
    if not ingress:
        raise TunnelValidationError("Ingress list cannot be empty")

    fallback = ingress[-1]
    if fallback.get("service") != "http_status:404" or "hostname" in fallback:
        raise TunnelValidationError("Final ingress rule must be service=http_status:404")

    seen_hostnames: set[str] = set()
    for entry in ingress[:-1]:
        hostname = entry.get("hostname")
        service = entry.get("service")

        if not hostname:
            raise TunnelValidationError("Ingress entry missing hostname")
        if hostname in seen_hostnames:
            raise TunnelValidationError(f"Duplicate hostname in ingress: {hostname}")
        seen_hostnames.add(hostname)

        validate_hostname(hostname)

        if not service:
            raise TunnelValidationError("Ingress entry missing service")

        validate_service_url(service)
