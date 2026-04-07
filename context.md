# TunnelDeck Backend Context

Last update: 2026-04-07

## Project Status
Backend MVP is implemented and runnable.

Reference API contract for frontend integration:
- `docs/API_CONTRACT.md`

## What Is Implemented

### Runtime and structure
- FastAPI app with base path `/api/v1`.
- Modular structure by domain: auth, security, docker, exposures, tunnel, audit.
- SQLite persistence with SQLAlchemy 2.0.
- Auto table creation on startup.
- Alembic migrations configured (`alembic/` + initial revision + `manage.py migrate`).
- Strict env-based config validation.
- CORS restricted to configured origins.
- `/docs` and `/openapi.json` disabled when `APP_ENV=production`.
- Global request middleware with `X-Request-ID` correlation.
- Global structured error envelope for non-2xx responses.
- JSON structured request/error logs.
- Container deployment files added for Coolify:
  - `Dockerfile`
  - `.dockerignore`

### Security model
- Firebase token verification in backend.
- Admin allowlist enforcement (`ALLOWED_ADMIN_EMAILS`).
- TOTP required for sensitive mutations via `X-TOTP-Code`.
- TOTP secrets encrypted at rest (Fernet key from env).
- In-memory rate limiting for TOTP-sensitive flows:
  - IP: `5/min` (default)
  - Admin email: `10/5min` (default)
- No endpoint for admin creation or TOTP enrollment via UI.
- CLI bootstrap for admin TOTP provisioning:
  - `python -m app.cli bootstrap-admin-totp --email ... --secret ...`

### Functional modules
- Docker module:
  - list containers
  - container details by id
- Exposures module:
  - list/create/update/delete exposure records
  - hostname/service/port/target validation
  - duplicate hostname prevention
- Tunnel module:
  - read/write cloudflared YAML
  - validate ingress rules
  - preserve fallback `http_status:404`
  - file lock for cross-process config updates
  - backup before write + backup retention (`CLOUDFLARED_BACKUP_MAX_FILES`)
  - explicit protected cloudflared restart endpoint (`POST /health/cloudflared/restart`)
  - manual backup restore support through CLI (`list-config-backups`, `restore-config-backup`)
  - restore CLI writes audit logs (`cloudflared.restore_backup`) for success/failure
  - platform-aware service manager support to avoid crashes on non-Linux hosts:
    - Linux: `systemctl`
    - macOS: `launchctl`
    - Windows: `sc`
    - Docker mode for containerized deployments (`CLOUDFLARED_CONTROL_MODE=docker`)
  - rollback on failure
- Audit module:
  - write audit logs for security and exposure actions
  - list audit entries

### Implemented endpoints
- `GET /api/v1/health`
- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/health/cloudflared`
- `POST /api/v1/health/cloudflared/restart`
- `GET /api/v1/auth/me`
- `GET /api/v1/dashboard/summary`
- `GET /api/v1/containers`
- `GET /api/v1/containers/{container_id}`
- `GET /api/v1/exposures`
- `POST /api/v1/exposures`
- `PUT /api/v1/exposures/{exposure_id}`
- `DELETE /api/v1/exposures/{exposure_id}`
- `POST /api/v1/security/verify-totp`
- `GET /api/v1/audit`

### Testing and tooling
- Unit tests and API integration tests (`TestClient` + mocks for Firebase/Docker/service manager).
- Current test status: passing locally (`27 passed`).
- Project files added:
  - `requirements.txt`
  - `.env.example`
  - `README.md`
  - `pytest.ini`
  - `.gitignore`

## Partially Implemented / Pending
- Cross-platform service control is best-effort:
  - Linux: expected production path (`systemctl`).
  - macOS/Windows: health works and no crash, but service lifecycle behavior depends on local service registration (`launchctl`/`sc`).
- In container-first deployments (Coolify standard Docker runtime), cloudflared restart operations can be unavailable if no supported service manager exists inside container.
- Coolify-ready path is now documented and supported through Docker control mode plus shared config volume.
- Metrics endpoint/exporter (Prometheus) is not implemented (logging-only observability in v1).

## Out Of Scope (Still Not Implemented)
- Creating admins from UI
- TOTP enrollment UI/self-service
- Arbitrary shell execution endpoint
- Generic filesystem editor
- Docker lifecycle management (create/delete/exec)
- Replacing Coolify

## Operational Notes
- `.env` must be at project root (`./.env`), not inside `.venv/`.
- Required env variables are documented in `.env.example`.
- `FIREBASE_PRIVATE_KEY` in `.env` must end with `"` and must not have a trailing comma.
- Dashboard depends on both Docker and cloudflared health checks:
  - Docker daemon unavailable -> `503`.
  - cloudflared service manager unavailable/missing -> no crash; health returns degraded status.

## Session Notes (2026-04-07)
- Fixed `.env` parsing issue (`python-dotenv`) caused by malformed `FIREBASE_PRIVATE_KEY` line.
- Added platform-aware cloudflared service controller to avoid `systemctl` crash on macOS.
- Extended `/api/v1/health/cloudflared` response with:
  - `platform_system`
  - `os_name`
  - `service_manager`
- Updated docs:
  - `README.md` with full setup/troubleshooting
  - `docs/API_CONTRACT.md` with updated cloudflared health response fields
- Implemented stability bundle:
  - tunnel config file lock + semantic `423` on lock timeout
  - error envelope + global exception handlers + request correlation header
  - readiness/liveness endpoints
  - pagination (`limit`/`offset` + `meta`) in `audit`, `exposures`, `containers`
  - backup retention (`N=20` default)
  - hardening checks/log warnings for production startup
- Added v1 stabilization items:
  - Alembic setup (`alembic.ini`, `alembic/`, initial migration `20260407_01`)
  - manual cloudflared restart endpoint (`POST /api/v1/health/cloudflared/restart`) with TOTP + audit
  - manual backup operations via CLI:
    - `python manage.py list-config-backups`
    - `python manage.py restore-config-backup --backup-id <id> --actor-email <email>`
  - management commands for migrations:
    - `python manage.py migrate`
    - `python manage.py makemigration -m \"...\"`
    - `python manage.py downgrade --revision <rev>`
    - `python manage.py stamp --revision head`
  - expanded tests (`27 passed`)
- Coolify/container hardening:
  - cloudflared control mode now supports Docker (`CLOUDFLARED_CONTROL_MODE=docker`)
  - cloudflared container target configurable (`CLOUDFLARED_DOCKER_CONTAINER_NAME`)
  - Dockerfile defaults tuned for container deployment (`/data` sqlite + `/data/cloudflared/config.yml`)
