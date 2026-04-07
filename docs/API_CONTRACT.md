# TunnelDeck API Contract (MVP)

Base URL: `/api/v1`

## Security Contract

### Headers
- Protected endpoints require:
  - `Authorization: Bearer <firebase_id_token>`
- Sensitive mutation endpoints additionally require:
  - `X-TOTP-Code: <6-digit-code>`

### Protected (read) endpoints
- `GET /health/cloudflared`
- `GET /auth/me`
- `GET /dashboard/summary`
- `GET /containers`
- `GET /containers/{container_id}`
- `GET /exposures`
- `GET /audit`
- `POST /security/verify-totp`

### Sensitive mutation endpoints (Auth + TOTP)
- `POST /exposures`
- `PUT /exposures/{exposure_id}`
- `DELETE /exposures/{exposure_id}`

## Common Error Responses
- `401 Unauthorized`
  - `{"detail": "Missing bearer token"}`
  - `{"detail": "Invalid or expired Firebase token"}`
  - `{"detail": "Firebase token missing required claims"}`
- `403 Forbidden`
  - `{"detail": "User is not in admin allowlist"}`
  - `{"detail": "Missing X-TOTP-Code header"}`
  - `{"detail": "TOTP code must be 6 digits"}`
  - `{"detail": "Invalid TOTP code"}`
  - `{"detail": "No TOTP secret configured for admin"}`
- `422 Unprocessable Entity` (validation errors / invalid parameters)
- `500 Internal Server Error` in controlled failure paths for tunnel/exposure operations

## Endpoints

### 1) Health

#### `GET /health`
Auth: No

Response `200`:
```json
{
  "status": "ok",
  "timestamp": "2026-04-07T10:15:30.123456+00:00"
}
```

#### `GET /health/cloudflared`
Auth: Bearer

Response `200`:
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

### 2) Auth

#### `GET /auth/me`
Auth: Bearer

Response `200`:
```json
{
  "uid": "firebase-uid",
  "email": "admin@example.com",
  "name": "Admin Name"
}
```

### 3) Dashboard

#### `GET /dashboard/summary`
Auth: Bearer

Response `200`:
```json
{
  "exposures": {
    "total": 3,
    "enabled": 2
  },
  "containers": {
    "total": 10,
    "running": 7
  },
  "cloudflared": {
    "service_name": "cloudflared",
    "status": "active",
    "is_active": true,
    "config_exists": true
  }
}
```

### 4) Containers

#### `GET /containers`
Auth: Bearer

Response `200`:
```json
{
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
      "labels": {
        "com.docker.compose.service": "web"
      },
      "networks": [
        "bridge"
      ],
      "created_at": "2026-04-07T10:15:30+00:00",
      "started_at": "2026-04-07T10:20:00+00:00"
    }
  ]
}
```

Possible errors:
- `503` Docker unavailable

#### `GET /containers/{container_id}`
Auth: Bearer

Path params:
- `container_id` (string)

Response `200`: same object shape as each `items[]` entry above.

Possible errors:
- `404` container not found
- `503` Docker unavailable

### 5) Exposures

## Exposure payload schema
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

Rules:
- `service_type`: `http` | `https`
- `target_port`: 1..65535
- `hostname`: valid FQDN, normalized to lowercase
- `target_host`: no scheme, no path (`localhost`, `127.0.0.1`, etc.)

## Exposure response object
```json
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
```

#### `GET /exposures`
Auth: Bearer

Response `200`:
```json
{
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

#### `POST /exposures`
Auth: Bearer + `X-TOTP-Code`

Body: Exposure payload schema

Response `201`: Exposure response object

Possible errors:
- `403` missing/invalid TOTP
- `409` hostname exists
- `422` container missing or validation fails
- `500` tunnel/config apply failure

#### `PUT /exposures/{exposure_id}`
Auth: Bearer + `X-TOTP-Code`

Body: Exposure payload schema

Response `200`: Exposure response object

Possible errors:
- `403` missing/invalid TOTP
- `404` exposure not found
- `409` hostname exists
- `422` validation/container missing
- `500` tunnel/config apply failure

#### `DELETE /exposures/{exposure_id}`
Auth: Bearer + `X-TOTP-Code`

Response `204`: empty body

Possible errors:
- `403` missing/invalid TOTP
- `404` exposure not found
- `500` tunnel/config apply failure

### 6) Security

#### `POST /security/verify-totp`
Auth: Bearer

Body:
```json
{
  "code": "123456"
}
```

Response `200`:
```json
{
  "valid": true
}
```

Possible errors:
- `403` invalid/missing/not-configured TOTP

### 7) Audit

#### `GET /audit?limit=100`
Auth: Bearer

Query params:
- `limit` integer, min `1`, max `500`, default `100`

Response `200`:
```json
{
  "entries": [
    {
      "id": 10,
      "actor_email": "admin@example.com",
      "action": "exposure.create",
      "resource_type": "exposure",
      "resource_id": "1",
      "success": true,
      "details": {
        "hostname": "app.example.com"
      },
      "error_message": null,
      "created_at": "2026-04-07T10:15:30"
    }
  ]
}
```

## Notes for Frontend
- No wildcard CORS in production.
- Mutations must always send `X-TOTP-Code`.
- Backend is source of truth for validation; frontend validations are UX-only.
- For `DELETE /exposures/{id}`, expect `204` with empty response body.
