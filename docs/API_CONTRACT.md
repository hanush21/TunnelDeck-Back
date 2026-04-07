# TunnelDeck API Contract (V1 Stable)

Base URL: `/api/v1`

## Headers

### Required on protected endpoints
- `Authorization: Bearer <firebase_id_token>`

### Required on sensitive mutations
- `X-TOTP-Code: <6-digit-code>`

### Returned on every response
- `X-Request-ID: <uuid>`

## Error Contract

All non-2xx responses use this envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": null,
    "request_id": "c99713f5-1aa7-4fa6-a12f-2f0d6dc0d6b8"
  }
}
```

Common `error.code` values:
- `unauthorized`, `forbidden`, `not_found`, `conflict`, `validation_error`
- `resource_locked` (HTTP 423)
- `rate_limit_exceeded` (HTTP 429)
- `service_unavailable`, `internal_error`

Rate-limited responses include:
- `Retry-After: <seconds>`

## Endpoints

### Health
- `GET /health` (public)
- `GET /health/live` (public)
- `GET /health/ready` (public)
- `GET /health/cloudflared` (protected)
- `POST /health/cloudflared/restart` (protected + TOTP)

#### `GET /health/live` response
```json
{
  "status": "alive",
  "timestamp": "2026-04-07T10:15:30.123456+00:00"
}
```

#### `GET /health/ready` response
```json
{
  "ready": true,
  "status": "ready",
  "timestamp": "2026-04-07T10:15:30.123456+00:00",
  "components": {
    "database": { "ready": true, "status": "ok" },
    "docker": { "ready": false, "status": "degraded", "detail": "..." },
    "cloudflared": {
      "ready": false,
      "status": "not_found",
      "service_manager": "launchctl",
      "platform_system": "darwin"
    }
  }
}
```

#### `POST /health/cloudflared/restart` response
```json
{
  "service_name": "cloudflared",
  "status": "active",
  "is_active": true,
  "config_exists": true,
  "platform_system": "linux",
  "os_name": "posix",
  "service_manager": "systemd"
}
```

### Auth
- `GET /auth/me` (protected)

### Dashboard
- `GET /dashboard/summary` (protected)

### Containers
- `GET /containers?limit=100&offset=0` (protected)
- `GET /containers/{container_id}` (protected)

`GET /containers` response:
```json
{
  "meta": {
    "total": 42,
    "limit": 100,
    "offset": 0
  },
  "items": [
    {
      "id": "d1e2f3",
      "name": "my-service",
      "image": "nginx:latest",
      "state": "running",
      "status": "running",
      "published_ports": [
        {
          "container_port": "80/tcp",
          "host_ip": "0.0.0.0",
          "host_port": "8080"
        }
      ],
      "labels": {"com.docker.compose.service": "web"},
      "networks": ["bridge"],
      "created_at": "2026-04-07T10:15:30+00:00",
      "started_at": "2026-04-07T10:20:00+00:00"
    }
  ]
}
```

### Exposures
- `GET /exposures?limit=100&offset=0` (protected)
- `POST /exposures` (protected + TOTP)
- `PUT /exposures/{exposure_id}` (protected + TOTP)
- `DELETE /exposures/{exposure_id}` (protected + TOTP)

Exposure payload:
```json
{
  "container_name": "my-service",
  "hostname": "app.example.com",
  "service_type": "http",
  "target_host": "localhost",
  "target_port": 3000,
  "enabled": true
}
```

`GET /exposures` response:
```json
{
  "meta": {
    "total": 3,
    "limit": 100,
    "offset": 0
  },
  "items": [
    {
      "id": 1,
      "container_name": "my-service",
      "hostname": "app.example.com",
      "service_type": "http",
      "target_host": "localhost",
      "target_port": 3000,
      "enabled": true,
      "created_by": "admin@example.com",
      "created_at": "2026-04-07T10:15:30",
      "updated_at": "2026-04-07T10:15:30"
    }
  ]
}
```

`DELETE /exposures/{id}` returns `204` with empty body.

### Security
- `POST /security/verify-totp` (protected)

Request:
```json
{
  "code": "123456"
}
```

Response:
```json
{
  "valid": true
}
```

### Audit
- `GET /audit?limit=100&offset=0` (protected)

Response:
```json
{
  "meta": {
    "total": 120,
    "limit": 100,
    "offset": 0
  },
  "entries": [
    {
      "id": 10,
      "actor_email": "admin@example.com",
      "action": "exposure.create",
      "resource_type": "exposure",
      "resource_id": "1",
      "success": true,
      "details": {
        "hostname": "app.example.com",
        "request_id": "c99713f5-1aa7-4fa6-a12f-2f0d6dc0d6b8"
      },
      "error_message": null,
      "created_at": "2026-04-07T10:15:30"
    }
  ]
}
```

## Frontend Notes
- Keep using existing success payloads; only list endpoints gained `meta`.
- Always read and log `X-Request-ID` for support/debug traces.
- For sensitive mutations, send `X-TOTP-Code` on every request.
- `POST /health/cloudflared/restart` is optional for UI; no required frontend changes if you do not expose a manual restart button.
