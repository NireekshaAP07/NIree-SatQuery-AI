# SatQuery AI: Production Readiness Assessment

While the MVP is fully functional and successfully integrates the frontend, backend, database, queue, and AI models, it is currently optimized for *local development*.

To make SatQuery AI **"Production Ready"**, we need to transition the infrastructure for scalability, data safety, and security. Here are the 5 major areas we need to tackle:

## 1. Container Topology & Web Servers ✅ **COMPLETED**
**Status**: Deployed — *2026-09-08*

**What was done:**
* **Backend API**: Updated `Dockerfile` to use `gunicorn` with 4 `uvicorn` workers (configurable via `GUNICORN_WORKERS` env), 2 threads per worker, 120s timeout, 5s keepalive. Added production env vars (`PYTHONUNBUFFERED`, `PYTHONDONTWRITEBYTECODE`).
* **Query Worker**: Added dedicated `worker` service in `docker-compose.yml` using same image, runs `python -m app.workers.query_worker`. Scales independently with its own resource limits (2 CPU, 2GB RAM).
* **Frontend**: Created multi-stage `frontend/Dockerfile` (builder → runner). Uses `output: 'standalone'` in `next.config.ts`, runs `npm run build` then `node server.js` as non-root user (UID 1001).
* **Docker Compose**: Expanded from 4 to 6 services (nginx, api, worker, frontend, db, redis). Added resource limits/reservations for all services. Removed live-reload volume mount from API.
* **Nginx**: Enabled `frontend` upstream in `nginx/nginx.conf`, added proxy location `/` for frontend, kept `/api/` and `/ws/` for backend.
* **Dockerignore**: Added `.dockerignore` at root and in `frontend/` to exclude dev files, caches, secrets, and build artifacts.

**Verification:**
* Frontend image builds successfully (~20s)
* Backend image builds successfully (~15+ min due to torch/CUDA deps)
* `docker compose config` validates without errors

## 2. Database Migrations (Alembic)
Currently, `app/main.py` runs `init_db()` which uses `Base.metadata.create_all()` to forcefully create tables on startup.
* **The Risk**: In production, if you change a database schema (e.g., add a column), `create_all()` will not alter existing tables, and manual alterations are risky.
* **The Fix**: We need to initialize **Alembic**, generate the initial migration script, and run migrations on startup instead of raw table creation.

## 3. Distributed Storage
Currently, satellite imagery is saved to a local Docker volume (`./data`) using `STORAGE_BACKEND=local`.
* **The Risk**: If you scale to multiple API servers or worker nodes, they won't share the same local filesystem. Docker volumes are also harder to back up.
* **The Fix**: Implement the S3 storage backend (`STORAGE_BACKEND=s3`) using AWS S3, Google Cloud Storage, or a self-hosted MinIO bucket.

## 4. Reverse Proxy & HTTPS
Currently, the backend runs on port `8000` and the frontend on `3000` over plain HTTP.
* **The Fix**: Add an **Nginx** or **Traefik** service to the docker-compose stack to act as a reverse proxy. It will route traffic to the frontend and backend under a single domain, and handle SSL/TLS certificate termination (HTTPS).

## 5. Security Hardening
* **CORS**: The `.env` currently allows `http://localhost:3000`. This needs to be strictly bound to your production domain.
* **Secrets Management**: Stop relying on `.env` files on disk. Production environments should inject secrets (like `OPENAI_API_KEY` and `POSTGRES_PASSWORD`) via a secure vault or Docker Secrets.

---

> [!TIP]
> **Recommendation**
> If you want to start making this production ready, I recommend we start with **#1 (Container Topology)** and **#2 (Alembic Migrations)**, as they are the foundational steps for any production deployment!
