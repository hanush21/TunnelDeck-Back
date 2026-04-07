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
- Strict env-based config validation.
- CORS restricted to configured origins.
- `/docs` and `/openapi.json` disabled when `APP_ENV=production`.

### Security model
- Firebase token verification in backend.
- Admin allowlist enforcement (`ALLOWED_ADMIN_EMAILS`).
- TOTP required for sensitive mutations via `X-TOTP-Code`.
- TOTP secrets encrypted at rest (Fernet key from env).
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
  - backup before write
  - platform-aware service manager support to avoid crashes on non-Linux hosts:
    - Linux: `systemctl`
    - macOS: `launchctl`
    - Windows: `sc`
  - rollback on failure
- Audit module:
  - write audit logs for security and exposure actions
  - list audit entries

### Implemented endpoints
- `GET /api/v1/health`
- `GET /api/v1/health/cloudflared`
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
- Unit tests for tunnel validation, exposure schema validation, and TOTP verification.
- Current test status: passing locally (`11 passed`).
- Project files added:
  - `requirements.txt`
  - `.env.example`
  - `README.md`
  - `pytest.ini`
  - `.gitignore`

## Partially Implemented / Pending
- No dedicated API endpoint to restart cloudflared manually (restart currently happens inside exposure mutation flow).
- No pagination/filtering for containers/exposures/audit beyond `audit.limit`.
- No formal DB migrations (Alembic not added; auto-create only).
- No integration/e2e tests for full auth + route flow.
- Error response format is default FastAPI style (`{"detail": ...}`), no custom global error envelope.
- Cross-platform service control is best-effort:
  - Linux: expected production path (`systemctl`).
  - macOS/Windows: health works and no crash, but service lifecycle behavior depends on local service registration (`launchctl`/`sc`).

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
