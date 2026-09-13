# SatQuery AI: Implementation Plan

---

## Part 1: Production Readiness

> Overview: Addresses the 4 remaining items after Container Topology (#1) was completed.

---

### Priority 1: Database Migrations (Alembic) — Foundation ✅ Done

**Current State**
- `app/main.py:32-34` — schema is managed by Alembic (`migrate` service runs `alembic upgrade head` at startup)
- `docker-compose.yml` — `migrate` service runs before `api` and `worker`

**Implementation Steps**
1. Initialize Alembic — `alembic init alembic` in the project root
2. Configure `alembic.ini` with SQLAlchemy URL from settings
3. Update `env.py` to use async engine and import models
4. Generate baseline migration from current models (`Session`, `ImageAsset`, `AnalysisRun`, `Finding`, `Report`, `Query`)
5. Add migration command to Docker entrypoint via dedicated `migrate` service

**Files Modified**
- `alembic.ini`
- `alembic/env.py`
- `docker-compose.yml` (migrate service added)

---

### Priority 2: Distributed Storage (S3 Backend) — Scalability ✅ Done

**Current State**
- `app/core/storage.py` has both `LocalStorageBackend` and `S3StorageBackend`
- `get_storage()` returns the correct backend based on `STORAGE_BACKEND` env var
- For Oracle Cloud deployment: `STORAGE_BACKEND=local` (200 GB boot volume)

**Files Modified**
- `app/core/storage.py`
- `app/core/config.py`

---

### Priority 3: Reverse Proxy & HTTP Server — Network ✅ Done

**Current State**
- `nginx/nginx.conf` — Nginx handles HTTP on port 80 (port 443 HTTPS for local SSL)
- Upstreams: `api:8000` (FastAPI/Gunicorn) and `frontend:3000` (Next.js)
- WebSocket upgrade headers included for `/api/v1/sessions/{id}/ws`
- Port 80 server block updated to proxy directly (no forced HTTP→HTTPS redirect) so tunnel/reverse-proxy deployments work

**Files Modified**
- `nginx/nginx.conf`

---

### Priority 4: Security Hardening — Defense in Depth 🔄 Deferred (post-SIH)

**Current State**
- CORS configured via `ALLOWED_ORIGINS` env var — set in `.env.prod` for Oracle deployment
- `SECRET_KEY` via env var
- Auth router (`app/routers/auth.py`) in place with JWT
- `SecurityMiddleware` adds headers

**Post-SIH TODO**
- Let's Encrypt SSL (certbot) on Oracle VM domain
- Move to `APP_ENV=production` with HTTPS-only CORS validation
- Docker Secrets for production credentials
- Dependency scanning (pip-audit)

---

## Part 2: MVP Deployment — Oracle Cloud Free Tier

> **₹0 forever. 4 ARM CPUs, 24 GB RAM. No cold starts. No credit required beyond identity verification.**

---

### What Was Changed for Oracle Deployment

#### [`Dockerfile`](file:///home/kishanravi/SatQuery_AI/Dockerfile)
```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

# BuildKit cache mounts — apt and pip packages NEVER re-downloaded on code changes
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev libpq-dev gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install GDAL==$(gdal-config --version) \
    && pip install -r requirements.txt

COPY . .   # ← only this layer rebuilds on code changes
```

**Result:** First build ~8 min. Every subsequent `git pull` + rebuild ~90 seconds.

#### [`requirements.txt`](file:///home/kishanravi/SatQuery_AI/requirements.txt)
Removed: `torch`, `torchvision`, `transformers`, `accelerate`, `sentencepiece`
- These are **3.3 GB of local GPU model dependencies not used in the Gemini API-based MVP**
- The VLM stub in `model_provider.py:51-56` handles this gracefully
- Moved to [`requirements-gpu.txt`](file:///home/kishanravi/SatQuery_AI/requirements-gpu.txt) for future local GPU dev

#### [`docker-compose.prod.yml`](file:///home/kishanravi/SatQuery_AI/docker-compose.prod.yml)
Simplified version of `docker-compose.yml`:
- No MinIO / minio-init (uses `STORAGE_BACKEND=local` on Oracle's 200 GB disk)
- No Docker secrets (uses `.env.prod` file directly)
- DB and Redis bound to `127.0.0.1` only (not publicly exposed)
- Gunicorn workers reduced to 2 (leaves headroom for the background worker)

#### [`.env.prod`](file:///home/kishanravi/SatQuery_AI/.env.prod)
Template for Oracle VM. Fill in: `POSTGRES_PASSWORD`, `SECRET_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `ALLOWED_ORIGINS`, `NEXT_PUBLIC_API_URL`.

---

### Oracle Cloud Deployment: Step-by-Step

#### Step 1 — Oracle Cloud Account (10 min)
1. Go to [cloud.oracle.com](https://cloud.oracle.com) → **Start for free**
2. Sign up with college/Gmail email
3. Credit card for identity only — **₹0 charged**
4. Home Region: **India (Hyderabad)**

#### Step 2 — Create the Free VM (5 min)
- Compute → Instances → Create Instance
- Image: `Ubuntu 22.04`
- Shape: **VM.Standard.A1.Flex** (Ampere ARM) → 4 OCPUs, 24 GB RAM
- Upload your SSH public key
- Note the **Public IP**

#### Step 3 — Open Port 80 in Firewall (5 min)
Oracle has two firewall layers — both must be opened:

**Oracle Security List** (in the web console):
- Networking → VCN → Security Lists → Default → Add Ingress Rule
- TCP port `80` from `0.0.0.0/0`

**OS firewall** (on the VM):
```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save
```

#### Step 4 — Install Docker (5 min)
```bash
ssh -i ~/.ssh/your_key ubuntu@YOUR_VM_PUBLIC_IP

curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh
sudo usermod -aG docker ubuntu && newgrp docker
```

#### Step 5 — Push Code & Clone on VM
```bash
# On your LOCAL machine first:
cd /home/kishanravi/SatQuery_AI
git add .
git commit -m "deploy: oracle cloud MVP"
git push origin master

# Then on the Oracle VM:
git clone https://github.com/YOUR_USERNAME/SatQuery_AI.git
cd SatQuery_AI
```

#### Step 6 — Fill in `.env.prod`
```bash
cp .env.prod .env.prod.real
nano .env.prod.real
```

Fill in:
```
POSTGRES_PASSWORD=StrongPassword123!
DATABASE_URL=postgresql+asyncpg://satquery:StrongPassword123!@db:5432/satquery_db
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_hex(64))">
ALLOWED_ORIGINS=http://YOUR_VM_PUBLIC_IP
GOOGLE_API_KEY=YOUR_GEMINI_API_KEY
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
NEXT_PUBLIC_API_URL=http://YOUR_VM_PUBLIC_IP/api/v1
NEXT_PUBLIC_WS_URL=ws://YOUR_VM_PUBLIC_IP/api/v1
```

#### Step 7 — Build & Deploy
```bash
export DOCKER_BUILDKIT=1
docker compose -f docker-compose.prod.yml --env-file .env.prod.real up -d --build
```

First build: ~8-12 minutes. ☕

#### Step 8 — Seed Demo Data
```bash
docker exec satquery_api python scripts/seed_demo.py
```

#### Step 9 — Verify
```bash
curl http://YOUR_VM_PUBLIC_IP/health
# → {"status":"ok","version":"0.1.0",...}
```

Open `http://YOUR_VM_PUBLIC_IP` in browser → **SatQuery AI is live.**

---

### Updating After Code Changes

```bash
# Local machine:
git add . && git commit -m "fix: something" && git push

# Oracle VM:
cd SatQuery_AI
git pull
DOCKER_BUILDKIT=1 docker compose -f docker-compose.prod.yml --env-file .env.prod.real up -d --build
# ~90 seconds — only the code layer rebuilds
```

---

### Auto-Start on VM Reboot

```bash
crontab -e
# Add:
@reboot cd /home/ubuntu/SatQuery_AI && DOCKER_BUILDKIT=1 docker compose -f docker-compose.prod.yml --env-file .env.prod.real up -d
```

---

### Cost Summary

| Service | Platform | Cost |
|:--------|:---------|:-----|
| Frontend + Backend + DB + Redis + Worker | Oracle Cloud Free Tier VM | **₹0 forever** |
| Object Storage | Local disk (200 GB on Oracle VM) | **₹0** |
| **Total** | | **₹0** |
