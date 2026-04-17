# TunnelDeck Backend Context

Last update: 2026-04-17

## Project Status
Backend MVP implemented and runnable. Two recent tunnel config improvements applied.

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
  - platform-aware service manager support:
    - Linux: `systemctl`
    - macOS: `launchctl`
    - Windows: `sc`
    - Docker mode (`CLOUDFLARED_CONTROL_MODE=docker`)
  - rollback on failure
  - **[NEW] External entry preservation**: on every config write, entries in config.yml whose
    hostnames are NOT in the DB are kept as-is (order: external first, DB entries, fallback 404).
    Entries with non-http/https service schemes (e.g. unix sockets) are always preserved untouched.
  - **[NEW] Auto-import from config**: on every exposure create/update/delete, entries in
    config.yml not yet in DB are automatically imported as Exposure records (http/https only).
    `container_name` defaults to `target_host` (editable after import). Import is idempotent.
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
- Current test status: passing locally (`27 passed`) — **tests not yet updated for auto-import**.
- Project files:
  - `requirements.txt`
  - `.env.example`
  - `README.md`
  - `pytest.ini`
  - `.gitignore`

## Partially Implemented / Pending

### Tests missing for recent changes
- No tests for `TunnelService.import_external_config_entries`.
- No tests for external entry preservation in `apply_exposure_config`.

### Missing endpoint
- No `POST /api/v1/exposures/sync-from-config` endpoint to trigger import on demand
  (currently import only fires as a side-effect of create/update/delete).

### Auto-import limitations
- `container_name` for imported entries defaults to `target_host` — requires manual edit after import.
- No audit log entry written for auto-imported exposures.
- Non-http/https ingress entries (unix sockets, etc.) are preserved in config but never importable.

### Platform notes
- macOS/Windows service lifecycle depends on local service registration (`launchctl`/`sc`).
- In container-first deployments (Coolify standard Docker runtime), cloudflared restart can be
  unavailable if no supported service manager exists inside container.

### Observability
- Metrics endpoint/exporter (Prometheus) not implemented (logging-only in v1).

## Out Of Scope (Still Not Implemented)
- Creating admins from UI
- TOTP enrollment UI/self-service
- Arbitrary shell execution endpoint
- Generic filesystem editor
- Docker lifecycle management (create/delete/exec)
- Replacing Coolify

## Operational Notes
- `.env` must be at project root (`./.env`), not inside `.venv/`.
- Required env variables documented in `.env.example`.
- `FIREBASE_PRIVATE_KEY` in `.env` must end with `"` and must not have a trailing comma.
- Dashboard depends on both Docker and cloudflared health checks:
  - Docker daemon unavailable → `503`.
  - cloudflared service manager unavailable/missing → no crash; health returns degraded status.

## Session Notes (2026-04-07)
- Fixed `.env` parsing issue (`python-dotenv`) caused by malformed `FIREBASE_PRIVATE_KEY` line.
- Added platform-aware cloudflared service controller to avoid `systemctl` crash on macOS.
- Extended `/api/v1/health/cloudflared` response with `platform_system`, `os_name`, `service_manager`.
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
  - management commands: `migrate`, `makemigration`, `downgrade`, `stamp`
  - expanded tests (`27 passed`)
- Coolify/container hardening:
  - Docker control mode (`CLOUDFLARED_CONTROL_MODE=docker`)
  - configurable container target (`CLOUDFLARED_DOCKER_CONTAINER_NAME`)
  - Dockerfile defaults tuned for container deployment (`/data` sqlite + `/data/cloudflared/config.yml`)

## Session Notes (2026-04-17)
- Tunnel config write logic changed from full-overwrite to merge:
  - External entries (hostnames not in DB) preserved first in ingress order.
  - Non-http/https entries always preserved unchanged.
  - Config-missing case now starts from scratch instead of crashing.
- Auto-import added: on each exposure mutation, `TunnelService.import_external_config_entries`
  reads config.yml and creates DB records for untracked http/https entries.
  Entry `container_name` defaults to `target_host` as editable placeholder.
