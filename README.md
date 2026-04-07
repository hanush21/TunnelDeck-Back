# TunnelDeck Backend MVP

Secure FastAPI backend for TunnelDeck with:
- Firebase ID token verification
- Admin email allowlist
- TOTP validation for sensitive mutations
- In-memory anti brute-force rate limiting for TOTP-sensitive flows
- Docker inspection through Docker SDK
- Exposure CRUD with safe cloudflared sync (lock + backup + rollback)
- Structured JSON logs with `X-Request-ID` correlation
- Audit logging

## Requirements

- Python 3.11+
- Access to Docker socket (`/var/run/docker.sock`) on the server
- Access to cloudflared config and service management
  - Linux: `systemctl`
  - macOS: `launchctl`
  - Windows: `sc`

## 1. Create virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Configure environment variables

```bash
cp .env.example .env
```

Important:
- The backend reads env from `./.env` (project root).
- Do not use `.venv/.env`.

Minimum required values to start:
- `ALLOWED_ADMIN_EMAILS`
- `TOTP_ENCRYPTION_KEY`
- `CORS_ALLOWED_ORIGINS`
- Firebase credentials using one option below

### Firebase credentials

Option A (recommended): service account file
- Download service account JSON from Firebase Console:
  - Project Settings -> Service accounts -> Generate new private key
- Set:
```env
FIREBASE_CREDENTIALS_FILE=/absolute/path/to/service-account.json
```
- You can leave `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY` empty in this mode.

Option B: inline values in `.env`
```env
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_CLIENT_EMAIL=firebase-adminsdk-xxx@your-project.iam.gserviceaccount.com
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
```

Generate `TOTP_ENCRYPTION_KEY`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

New operational envs (already in `.env.example`):
- `CLOUDFLARED_BACKUP_MAX_FILES` (default `20`)
- `TUNNEL_CONFIG_LOCK_PATH` (default `./backups/cloudflared/config.lock`)
- `TUNNEL_CONFIG_LOCK_TIMEOUT_SECONDS` (default `10`)
- `RATE_LIMIT_TOTP_IP_MAX` / `RATE_LIMIT_TOTP_IP_WINDOW_SECONDS`
- `RATE_LIMIT_TOTP_EMAIL_MAX` / `RATE_LIMIT_TOTP_EMAIL_WINDOW_SECONDS`

## 3. Run the backend

Preferred (Django-style command):
```bash
source .venv/bin/activate
python manage.py runserver
```

With custom host/port:
```bash
python manage.py runserver --host 0.0.0.0 --port 8000
```

Development reload mode:
```bash
python manage.py runserver --reload
```

Direct uvicorn (equivalent):

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API base path:
- `/api/v1`

API contract for frontend:
- `docs/API_CONTRACT.md`

Health endpoints:
- `GET /api/v1/health`
- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/health/cloudflared`
- `POST /api/v1/health/cloudflared/restart` (requires auth + TOTP)

## 3.1 Database migrations (Alembic)

Apply migrations:
```bash
source .venv/bin/activate
python manage.py migrate
```

Create a new migration after model changes:
```bash
python manage.py makemigration -m "your message"
python manage.py migrate
```

Rollback one migration:
```bash
python manage.py downgrade --revision -1
```

If your DB already existed before Alembic (tables already created), mark it first:
```bash
python manage.py stamp --revision head
```

## 4. Bootstrap admin access with TOTP

1. Add admin email to allowlist in `.env`:
```env
ALLOWED_ADMIN_EMAILS=admin1@example.com,admin2@example.com
```

2. Generate a TOTP secret (Base32):
```bash
source .venv/bin/activate
python -c "import pyotp; print(pyotp.random_base32())"
```

3. Store secret in backend DB for that admin:
```bash
source .venv/bin/activate
python manage.py bootstrap-admin-totp --email admin1@example.com --secret YOUR_BASE32_SECRET
```

Equivalent direct command:
```bash
python -m app.cli bootstrap-admin-totp --email admin1@example.com --secret YOUR_BASE32_SECRET
```

4. Add the same secret to an authenticator app:
- Google Authenticator
- Aegis
- 2FAS
- Authy-compatible apps

After this:
- Read endpoints require Firebase bearer token.
- Sensitive mutation endpoints require Firebase bearer token and `X-TOTP-Code`.
- On rate limit exceed, API returns `429` + `Retry-After`.

## 4.1 Manual cloudflared backup restore (CLI)

List latest backups:
```bash
source .venv/bin/activate
python manage.py list-config-backups --limit 20
```

Restore by backup id:
```bash
python manage.py restore-config-backup --backup-id 12 --actor-email admin@example.com
```

Optional custom reason in backup metadata:
```bash
python manage.py restore-config-backup --backup-id 12 --actor-email admin@example.com --reason "manual emergency rollback"
```

## 5. Run tests

```bash
source .venv/bin/activate
python manage.py test
```

Equivalent direct command:
```bash
pytest -q
```

## 6. Common errors

`ALLOWED_ADMIN_EMAILS must include at least one admin email`
- `.env` is missing or loaded from wrong location.
- Ensure `./.env` exists at repo root and contains `ALLOWED_ADMIN_EMAILS`.

`Firebase credentials missing`
- Configure either `FIREBASE_CREDENTIALS_FILE` or full inline `FIREBASE_*` vars.

`Docker daemon unavailable`
- Check Docker is running and backend has permission to access `DOCKER_SOCKET_PATH`.

`systemctl` not found on macOS/Windows
- Expected. Backend uses platform-aware service manager detection and reports degraded cloudflared status instead of crashing.

## 7. Deploy on Coolify (Docker)

Added files:
- `Dockerfile`
- `.dockerignore`

### Coolify setup

1. Source:
- Use this repository.
- Build pack: `Dockerfile`.

2. Network:
- Internal/app port: `8000`.

3. Persistent storage (important for SQLite):
- Add a persistent volume mounted at `/data`.

4. Shared cloudflared config storage (required for exposure sync):
- Use a shared persistent volume between:
  - this backend container
  - your `cloudflared` container
- Mount it at least as:
  - Backend: `/data/cloudflared`
  - Cloudflared container: the path where it reads `config.yml`
- Recommended backend env:
  - `CLOUDFLARED_CONFIG_PATH=/data/cloudflared/config.yml`

5. Environment variables (minimum):
- `APP_ENV=production`
- `APP_HOST=0.0.0.0`
- `APP_PORT=8000`
- `DATABASE_URL=sqlite:////data/tunneldeck.db`
- `CLOUDFLARED_CONTROL_MODE=docker`
- `CLOUDFLARED_DOCKER_CONTAINER_NAME=cloudflared` (or your real container name)
- `CLOUDFLARED_CONFIG_PATH=/data/cloudflared/config.yml`
- `CLOUDFLARED_BACKUP_DIR=/data/backups/cloudflared`
- `TUNNEL_CONFIG_LOCK_PATH=/data/backups/cloudflared/config.lock`
- `ALLOWED_ADMIN_EMAILS=...`
- `TOTP_ENCRYPTION_KEY=...`
- `CORS_ALLOWED_ORIGINS=https://your-frontend-domain`
- Firebase credentials:
  - Either `FIREBASE_CREDENTIALS_FILE` (with mounted secret file), or
  - `FIREBASE_PROJECT_ID` + `FIREBASE_CLIENT_EMAIL` + `FIREBASE_PRIVATE_KEY`

6. Required mount for Docker operations:
- Docker socket (required for container listing and cloudflared restart in docker mode):
  - Host: `/var/run/docker.sock`
  - Container: `/var/run/docker.sock`

### SQLite for single-user use

Yes, for your current scenario (single admin / low load), SQLite is a good and pragmatic choice.
Use the `/data` volume so DB and backups survive redeploys/restarts.

### Important cloudflared note in containers

In Coolify/container deployments, configure:
- `CLOUDFLARED_CONTROL_MODE=docker`
- valid `CLOUDFLARED_DOCKER_CONTAINER_NAME`
- mounted `/var/run/docker.sock`
- shared volume for `CLOUDFLARED_CONFIG_PATH`

Without that setup, restart/apply operations can fail.

## Security notes

- Never commit `.env` or Firebase service-account JSON.
- Keep this backend internal/admin-only.
- Do not expose arbitrary shell execution.
- In production, run as non-root user and apply least privilege on config files and docker socket access.
- Persist and monitor `X-Request-ID` from responses for incident/debug tracing.
