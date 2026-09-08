# SatQuery AI: Production Readiness Implementation Plan

## Overview
This plan addresses the 4 remaining items from `PRODUCTION_READINESS.md` after Container Topology (#1) was completed.

---

## Priority 1: Database Migrations (Alembic) — Foundation

### Current State
- `app/main.py:32-34` runs `init_db()` using `Base.metadata.create_all()` only in development
- `satquery_backend/app/db/database.py:35-49` contains `init_db()` that forcefully creates tables
- No migration system exists — schema changes require manual SQL or table drops

### Implementation Steps

1. **Initialize Alembic**
   - Run `alembic init app/db/migrations` in the backend directory
   - Configure `alembic.ini` with SQLAlchemy URL from settings
   - Update `env.py` to use async engine and import models

2. **Generate Initial Migration**
   - Create baseline migration from current models (`SessionModel`, `ImageAssetModel`, `AnalysisJobModel`, `FindingModel`, `ReportModel`)
   - Review generated migration for correctness

3. **Update Startup Logic**
   - Replace `init_db()` call in `app/main.py:33` with `alembic upgrade head`
   - Add migration command to Docker entrypoint or startup script
   - Keep `create_all()` as fallback for fresh dev databases (optional)

4. **Add Migration Utilities**
   - Create `app/db/migrate.py` with `run_migrations()` function
   - Add `make migration "message"` helper script

### Files to Modify
- `satquery_backend/alembic.ini` (new)
- `satquery_backend/app/db/migrations/` (new directory)
- `satquery_backend/app/db/migrate.py` (new)
- `app/main.py` (modify lifespan)
- `docker-compose.yml` (add migration step to api service command)

### Verification
- Run migrations on fresh DB → tables created correctly
- Modify a model (e.g., add column) → generate migration → apply → schema updated
- Rollback migration → schema reverts

---

## Priority 2: Distributed Storage (S3 Backend) — Scalability

### Current State
- `app/core/storage.py` has `LocalStorageBackend` only
- `get_storage()` raises `NotImplementedError` for `s3` backend
- Files stored in Docker volume `./data` (not shared across nodes)
- Assets router uses `storage.save_upload()` and `storage.get_path()`

### Implementation Steps

1. **Create S3StorageBackend Class**
   - Use `boto3` or `aioboto3` for async S3 operations
   - Implement same interface as `LocalStorageBackend`:
     - `save_upload(bytes, filename, subdir) -> str` (returns S3 key)
     - `get_path(key) -> str` (returns presigned URL or S3 URI)
     - `delete(key) -> None`
     - `save_derived(bytes, filename) -> str`
   - Support S3-compatible endpoints (MinIO, GCS, R2, etc.)

2. **Add S3 Configuration to Settings**
   - Add `s3_bucket_name`, `s3_endpoint_url`, `s3_region`, `s3_access_key_id`, `s3_secret_access_key` to `app/core/config.py`
   - Validate required fields when `storage_backend == "s3"`

3. **Update get_storage() Factory**
   - Return `S3StorageBackend` when `STORAGE_BACKEND=s3`
   - Pass config from settings

4. **Update Assets Router for S3**
   - `storage.save_upload()` returns S3 key → store in DB
   - `storage.get_path()` returns presigned URL for preview/download
   - Preview endpoint: generate presigned URL for cached PNG or stream from S3

5. **Docker Compose Updates**
   - Remove `satquery_data` volume mount from `api` and `worker` services when using S3
   - Add S3 env vars to `.env.example`

### Files to Modify
- `app/core/storage.py` (add S3StorageBackend)
- `app/core/config.py` (add S3 settings)
- `app/routers/assets.py` (handle S3 paths/URLs)
- `docker-compose.yml` (conditional volume mounts)
- `.env.example` (add S3 variables)

### Verification
- Set `STORAGE_BACKEND=s3` with MinIO local → upload asset → stored in bucket
- List assets → metadata correct
- Get preview → serves via presigned URL
- Delete asset → removed from S3 and DB

---

## Priority 3: Reverse Proxy & HTTPS — Network Security

### Current State
- `nginx/nginx.conf` already has:
  - HTTP→HTTPS redirect (port 80→443)
  - SSL termination with certs in `./nginx/certs/`
  - Upstreams for `backend` (api:8000) and `frontend` (frontend:3000)
  - Proxy config for `/api/`, `/ws/`, and `/`
- Certs are self-signed placeholders (`cert.pem`, `key.pem`)

### Implementation Steps

1. **Production SSL Certificates**
   - Replace self-signed certs with Let's Encrypt or CA-signed certs
   - Document cert renewal process (certbot or ACME client)
   - Add cert validation to CI/CD

2. **Nginx Hardening**
   - Add security headers (HSTS, CSP, X-Frame-Options, etc.)
   - Rate limiting for `/api/` endpoints
   - Request size limits matching `MAX_UPLOAD_SIZE_MB`
   - Hide server version

3. **Docker Compose for Production**
   - Create `docker-compose.prod.yml` with:
     - No exposed DB/Redis ports (internal only)
     - Nginx as only public entrypoint
     - Resource limits tuned for production
     - Healthchecks for all services

4. **Environment-Specific Config**
   - Separate `.env.production` template
   - `ALLOWED_ORIGINS` set to production domain only
   - `APP_ENV=production`

### Files to Modify
- `nginx/nginx.conf` (add security headers, rate limiting)
- `docker-compose.yml` (create production override or separate file)
- `.env.example` (add production template)
- Documentation for SSL setup

### Verification
- HTTPS works with valid cert (browser shows 🔒)
- HTTP redirects to HTTPS
- Security headers present in responses
- Rate limiting triggers on abuse
- No internal ports exposed externally

---

## Priority 4: Security Hardening — Defense in Depth

### Current State
- CORS allows `http://localhost:3000,http://localhost:5173` (hardcoded in `.env`)
- Secrets in `.env` file on disk
- `SECRET_KEY` is placeholder
- No API authentication visible in routers (auth router exists but not inspected)

### Implementation Steps

1. **CORS Lockdown**
   - Validate `ALLOWED_ORIGINS` parsing in production
   - Reject `*` or localhost in production mode
   - Add startup warning if `APP_ENV=production` but origins contain localhost

2. **Secrets Management**
   - Remove sensitive values from `.env.example` (keep placeholders)
   - Document Docker Secrets usage:
     - `POSTGRES_PASSWORD` → `/run/secrets/postgres_password`
     - `OPENAI_API_KEY` → `/run/secrets/openai_api_key`
     - `SECRET_KEY` → `/run/secrets/secret_key`
   - Update `config.py` to read from Docker Secrets files when present

3. **API Authentication**
   - Inspect `app/routers/auth.py` for current implementation
   - Ensure JWT tokens have expiry, refresh mechanism
   - Add API key authentication for service-to-service (worker→api)

4. **Security Headers & Middleware**
   - Verify `SecurityMiddleware` in `app/middleware/security.py` adds headers
   - Add request validation (size, content-type)
   - Implement audit logging for sensitive operations

5. **Dependency Scanning**
   - Add `pip-audit` or `safety` to CI
   - Pin all dependencies (already done in requirements.txt)

### Files to Modify
- `app/core/config.py` (read secrets from files, validate CORS)
- `app/middleware/security.py` (verify/enhance headers)
- `app/routers/auth.py` (review auth implementation)
- `docker-compose.yml` (add secrets mounts)
- `.env.example` (sanitize)
- CI/CD pipeline (add dependency scanning)

### Verification
- Production deploy rejects localhost CORS
- Secrets not visible in `docker inspect` or container fs
- Auth required for all `/api/v1/*` endpoints
- Security headers present
- No known vulnerabilities in dependencies

---

## Implementation Order & Dependencies

```
Week 1: Priority 1 (Alembic) — Independent, foundational
Week 2: Priority 2 (S3) — Independent, enables horizontal scaling
Week 3: Priority 3 (HTTPS) — Depends on DNS/domain, can parallelize
Week 4: Priority 4 (Security) — Depends on 1-3, final hardening
```

---

## Approval Request

Please review this plan and confirm:
1. **Order of implementation** — Any priority changes?
2. **S3 Provider** — AWS S3, MinIO, GCS, Cloudflare R2, or other?
3. **SSL Approach** — Let's Encrypt (auto), manual certs, or cloud provider (ACM, etc.)?
4. **Auth Scope** — JWT only, or also API keys for service-to-service?
5. **Timeline** — Start with Priority 1 (Alembic) immediately?

Once approved, I'll begin with **Priority 1: Alembic Migrations**.