# TunnelDeck Backend MVP

Secure FastAPI backend for TunnelDeck with:
- Firebase ID token verification
- Admin email allowlist
- TOTP validation for sensitive mutations
- Docker inspection through Docker SDK
- Exposure CRUD with safe cloudflared sync (backup + rollback)
- Audit logging

## Requirements

- Python 3.11+
- Access to Docker socket (`/var/run/docker.sock`) on the server
- Access to cloudflared config and service management (`systemd`) on the server

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

## 3. Run the backend

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API base path:
- `/api/v1`

API contract for frontend:
- `docs/API_CONTRACT.md`

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

## 5. Run tests

```bash
source .venv/bin/activate
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

## Security notes

- Never commit `.env` or Firebase service-account JSON.
- Keep this backend internal/admin-only.
- Do not expose arbitrary shell execution.
