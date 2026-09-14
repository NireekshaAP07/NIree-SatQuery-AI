# 🚀 SatQuery AI — Complete Cloud Deployment Guide

This guide covers everything required to deploy the complete SatQuery AI stack to the cloud from scratch.

---

## Table of Contents
1. [Architecture & Topology Overview](#1-architecture--topology-overview)
2. [Recommended Cloud Platform: Oracle Cloud Free Tier](#2-recommended-cloud-platform-oracle-cloud-free-tier)
3. [Pre-deployment Preparation (Local Machine)](#3-pre-deployment-preparation-local-machine)
4. [Step-by-Step Server Setup](#4-step-by-step-server-setup)
5. [Firewall & Network Configuration](#5-firewall--network-configuration)
6. [Docker Installation & Setup](#6-docker-installation--setup)
7. [Deploying SatQuery AI on the Server](#7-deploying-satquery-ai-on-the-server)
8. [Database Seeding & Verification](#8-database-seeding--verification)
9. [Setting Up a Custom Domain & Free SSL (Certbot)](#9-setting-up-a-custom-domain--free-ssl-certbot)
10. [Maintenance, Zero-Downtime Updates & Troubleshooting](#10-maintenance-zero-downtime-updates--troubleshooting)

---

## 1. Architecture & Topology Overview

SatQuery AI uses containerized microservices managed via **Docker Compose**:

```
                       Internet (Browser Clients)
                                  │
                                  ▼
                         [Nginx Reverse Proxy]
                             (:80 / :443)
                            ┌─────┴─────┐
             /api/* & /ws/* │           │ /* (Web UI)
                            ▼           ▼
                   [FastAPI API]   [Next.js Frontend]
                      (:8000)           (:3000)
                         │                 │
                ┌────────┴────────┐        │
                ▼                 ▼        │
         [PostgreSQL + PostGIS] [Redis]    │
               (Storage)      (Task Queue) │
                                  │        │
                                  ▼        ▼
                          [Background Worker]
```

### Services Deployed in Production (`docker-compose.prod.yml`):
| Service | Image/Context | Description |
|:---|:---|:---|
| **nginx** | `nginx:alpine` | Gateway reverse proxy, handles HTTP, WebSocket upgrades, gzip & timeouts |
| **migrate** | `./Dockerfile` | Runs `alembic upgrade head` before API starts, then exits |
| **api** | `./Dockerfile` | FastAPI backend with Gunicorn workers |
| **worker** | `./Dockerfile` | Async background analysis worker (`python -m app.workers.query_worker`) |
| **frontend** | `./frontend/Dockerfile` | Production Next.js web application |
| **db** | `postgis/postgis:16-3.4` | PostgreSQL with PostGIS spatial extensions (loopback only) |
| **redis** | `redis:7.4-alpine` | Redis task queue and pub/sub broker (loopback only) |

---

## 2. Recommended Cloud Platform: Oracle Cloud Free Tier

### Why Oracle Cloud?
- **Cost**: **₹0 / $0 Forever** (Always Free Tier)
- **Compute**: Ampere A1 ARM Compute: **4 OCPUs (vCPUs), 24 GB RAM**
- **Disk Storage**: **200 GB NVMe Boot Volume** (free)
- **Bandwidth**: **10 TB/month outbound**
- **No Cold Starts**: Your API and database run 24/7 without sleeping.

*(Alternative: Any Ubuntu 22.04/24.04 x86 or ARM VPS with ≥4GB RAM on AWS EC2, DigitalOcean, Hetzner, or GCP will work identically).*

---

## 3. Pre-deployment Preparation (Local Machine)

Before deploying, ensure your Git repository is updated and pushed to your remote repository (e.g., GitHub):

```bash
# In your local SatQuery_AI directory:
git add .
git commit -m "feat: ready for cloud deployment"
git push origin master
```

Make sure you have your API keys ready:
- **Google Gemini API Key**: [Google AI Studio](https://aistudio.google.com/)

---

## 4. Step-by-Step Server Setup

### 4.1. Provision Oracle Cloud VM
1. Go to [cloud.oracle.com](https://cloud.oracle.com) and sign in.
2. In the dashboard, navigate to: **Compute → Instances → Create Instance**.
3. Fill in the parameters:
   - **Name**: `satquery-prod`
   - **Image**: `Ubuntu 22.04` (or `Ubuntu 24.04`)
   - **Shape**: Click *Change Shape* → select **Ampere (ARM)** → **VM.Standard.A1.Flex**
   - **OCPUs**: `4`
   - **Memory**: `24 GB`
   - **Networking**: Select or create default VCN with a Public Subnet. Ensure **Assign a public IPv4 address** is selected.
   - **SSH Keys**: Download the generated private key or paste your local public key (`~/.ssh/id_rsa.pub`).
4. Click **Create**. Note the assigned **Public IP Address** (e.g., `141.148.x.x`).

---

## 5. Firewall & Network Configuration

Oracle Cloud requires two firewall layers to be opened:

### 5.1. Oracle Cloud Security List (VCN Web Console)
1. In Oracle Cloud Console, go to **Networking → Virtual Cloud Networks (VCN)**.
2. Click your VCN → click **Security Lists** → click **Default Security List for...**.
3. Under **Ingress Rules**, click **Add Ingress Rules**:
   - **Source CIDR**: `0.0.0.0/0`
   - **IP Protocol**: `TCP`
   - **Destination Port Range**: `80,443`
   - **Description**: `HTTP and HTTPS for SatQuery AI`
4. Click **Add Ingress Rules**.

### 5.2. Server OS Firewall (iptables)
SSH into your server:
```bash
ssh -i /path/to/your/ssh_key ubuntu@<YOUR_VM_PUBLIC_IP>
```

Open ports 80 and 443 in the host firewall:
```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save || sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save
```

---

## 6. Docker Installation & Setup

Run these commands inside your VM to install Docker Engine and Docker Compose:

```bash
# Update system packages
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker via official convenience script
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add current user to docker group (avoid sudo for docker commands)
sudo usermod -aG docker ubuntu
newgrp docker

# Verify installation
docker --version
docker compose version
```

---

## 7. Deploying SatQuery AI on the Server

### 7.1. Clone the Codebase
```bash
cd /home/ubuntu
git clone https://github.com/<YOUR_USERNAME>/SatQuery_AI.git
cd SatQuery_AI
```

### 7.2. Configure Environment Variables
Create `.env.prod.real` from the template:
```bash
cp .env.prod .env.prod.real
nano .env.prod.real
```

Generate a secure 64-character secret key:
```bash
python3 -c "import secrets; print(secrets.token_hex(64))"
```

Fill out the fields in `.env.prod.real`:
```env
# ── DATABASE ──────────────────────────────────────────────────────────────────
POSTGRES_USER=satquery
POSTGRES_PASSWORD=YourStrongDatabasePassword123!
POSTGRES_DB=satquery_db
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://satquery:YourStrongDatabasePassword123!@db:5432/satquery_db

# ── REDIS ─────────────────────────────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0

# ── STORAGE ───────────────────────────────────────────────────────────────────
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=./data

# ── SECURITY ──────────────────────────────────────────────────────────────────
SECRET_KEY=<PASTE_THE_GENERATED_64_CHAR_HEX_HERE>
ALLOWED_ORIGINS=http://<YOUR_VM_PUBLIC_IP>

# ── APP CONFIG ────────────────────────────────────────────────────────────────
APP_ENV=development

# ── VLM (VISION-LANGUAGE MODEL) ────────────────────────────────────────────────
# If using fine-tuned PaliGemma weights:
VLM_MODEL_NAME=./data/weights/satquery-paligemma-lora
VLM_DEVICE=cpu    # set to cuda if GPU is present

# ── GEMINI LLM ORCHESTRATOR & REPORT AGENT ────────────────────────────────────
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
GOOGLE_API_KEY=<YOUR_GOOGLE_GEMINI_API_KEY>
GEMINI_API_KEY=<YOUR_GOOGLE_GEMINI_API_KEY>
GEMINI_MODEL=gemini-2.0-flash

# ── FRONTEND NETWORKING ───────────────────────────────────────────────────────
NEXT_PUBLIC_API_URL=http://<YOUR_VM_PUBLIC_IP>/api/v1
NEXT_PUBLIC_WS_URL=ws://<YOUR_VM_PUBLIC_IP>/api/v1
```

Save and exit (`Ctrl + O`, `Enter`, then `Ctrl + X`).

### 7.3. Build & Launch Containers
SatQuery AI includes optimized multi-stage Docker build caching:

```bash
export DOCKER_BUILDKIT=1
docker compose -f docker-compose.prod.yml --env-file .env.prod.real up -d --build
```
> ⏱️ *Note:* The initial build installs GDAL, spatial packages, and compiles Next.js. It takes ~8-12 minutes. Subsequent builds will take ~60-90 seconds.

### 7.4. Inspect Running Services
Check container status:
```bash
docker compose -f docker-compose.prod.yml ps
```
You should see all 6 services (`satquery_nginx`, `satquery_api`, `satquery_worker`, `satquery_frontend`, `satquery_db`, `satquery_redis`) up and healthy, while `satquery_migrate` exits with status `0` (migration complete).

To tail backend logs:
```bash
docker logs -f satquery_api
```

---

## 8. Database Seeding & Verification

### 8.1. Run Demo Data Seeding
Populate your production database with initial sample satellite sessions and queries:
```bash
docker exec satquery_api python scripts/seed_demo.py
```

### 8.2. Test the Application
1. Open your browser and navigate to:
   ```
   http://<YOUR_VM_PUBLIC_IP>
   ```
2. Test the API health endpoint:
   ```bash
   curl http://localhost/api/v1/health
   # or
   curl http://<YOUR_VM_PUBLIC_IP>/api/v1/health
   ```
   *Expected Response:*
   ```json
   {"status":"ok","version":"0.1.0","app_name":"SatQuery AI"}
   ```

---

## 9. Setting Up a Custom Domain & Free SSL (Certbot)

To switch from plain HTTP (`http://IP`) to production HTTPS (`https://yourdomain.com`):

### 9.1. Point DNS Records
Add an **A record** in your domain registrar (Cloudflare, Namecheap, GoDaddy):
- **Host / Name**: `satquery` (or `@` for apex domain)
- **Value**: `<YOUR_VM_PUBLIC_IP>`

### 9.2. Obtain Let's Encrypt Certificate
Install Certbot on the host:
```bash
sudo apt-get install -y certbot
```

Stop Nginx temporarily to obtain the certificate:
```bash
docker compose -f docker-compose.prod.yml stop nginx
sudo certbot certonly --standalone -d yourdomain.com
docker compose -f docker-compose.prod.yml start nginx
```

### 9.3. Mount Certificates into Nginx
Update `nginx/nginx.conf` and `docker-compose.prod.yml` to mount `/etc/letsencrypt/live/yourdomain.com/` into `/etc/nginx/certs/`:
- `fullchain.pem` → `cert.pem`
- `privkey.pem` → `key.pem`

Update `.env.prod.real`:
```env
ALLOWED_ORIGINS=https://yourdomain.com
NEXT_PUBLIC_API_URL=https://yourdomain.com/api/v1
NEXT_PUBLIC_WS_URL=wss://yourdomain.com/api/v1
APP_ENV=production
```

Recreate the containers:
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod.real up -d --build frontend nginx
```

---

## 10. Maintenance, Zero-Downtime Updates & Troubleshooting

### 10.1. Auto-Start on System Reboot
Ensure containers restart automatically if the cloud instance restarts:
```bash
crontab -e
```
Add the following line to the bottom:
```bash
@reboot cd /home/ubuntu/SatQuery_AI && DOCKER_BUILDKIT=1 docker compose -f docker-compose.prod.yml --env-file .env.prod.real up -d
```

### 10.2. Deploying New Code Changes
When you push new changes to GitHub:
```bash
cd /home/ubuntu/SatQuery_AI
git pull origin master
DOCKER_BUILDKIT=1 docker compose -f docker-compose.prod.yml --env-file .env.prod.real up -d --build
```
*Docker will only rebuild changed code layers, updating services in ~60-90 seconds.*

### 10.3. Useful Commands
- **View logs across all services**:
  ```bash
  docker compose -f docker-compose.prod.yml logs -f
  ```
- **View worker logs only**:
  ```bash
  docker logs -f satquery_worker
  ```
- **Restart a specific service**:
  ```bash
  docker compose -f docker-compose.prod.yml restart api
  ```
- **Clean unused docker cache/images**:
  ```bash
  docker image prune -f
  ```
- **Backup PostgreSQL database**:
  ```bash
  docker exec satquery_db pg_dump -U satquery satquery_db > satquery_backup_$(date +%F).sql
  ```
