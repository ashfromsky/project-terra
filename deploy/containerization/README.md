# PROJECT TERRA — Containerization & Production Deployment Architecture

This directory provides the production-grade, reproducible containerization and cloud deployment infrastructure for **PROJECT TERRA** (Ecosystem Response & Resilience Intelligence).

---

## 1. Architecture Overview

PROJECT TERRA comprises five distinct application processes orchestrated across Docker internal networking and Cloudflare Edge infrastructure:

```text
                               +----------------------------------+
                               |     Cloudflare Pages Edge        |
                               | (React 19 / Vite SPA Frontend)   |
                               |      https://app.example.com     |
                               +-----------------+----------------+
                                                 |
                                     HTTPS REST  | (HttpOnly Cookies,
                                     API Calls   |  SameSite=Lax)
                                                 v
+ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
  PRODUCTION VPS (Docker Compose: `compose.prod.yaml`)                                              |
                                                                                                    |
  [ Optional Ingress: Cloudflare Tunnel (`cloudflared`) or Nginx/Caddy Reverse Proxy ]              |
                                                 |                                                  |
                                                 v Internal Port 8000                               |
       +--------------------------------------------------------------------------------------+     |
       |                                      CORE API                                        |     |
       |                   FastAPI + Granian Application (Port 8000)                          |     |
       |               (Auth, Regions, Layers, Assessments, Data Sources Proxy)                |     |
       +-----------------------+----------------------------------+---------------------------+     |
                               |                                  |                                 |
              Internal HTTP    |                                  | Shared DATABASE_URL             |
              `http://ghs:8080`|                                  | `terra_core`                    |
                               v                                  v                                 |
       +-------------------------------+                  +---------------+                         |
       |            GHS API            |                  |  CORE WORKER  |                         |
       | FastAPI + Granian (Port 8080) |                  | (terra-worker)|                         |
       | (Ingestion, Transforms, Zarr) |                  +-------+-------+                         |
       +---------------+---------------+                          |                                 |
                       | Shared GHS_DATABASE_URL                  | Resolves Granules /             |
                       | `terra_ghs`                              | Fetches Prepared Datasets       |
                       v                                          +----------------+                |
               +---------------+                                                   |                |
               |  GHS WORKER   |                                                   |                |
               | (WorkerRunner)|                                                   |                |
               +-------+-------+                                                   |                |
                       |                                                           |                |
                       |                  Docker Internal Network (`terra-internal`)|                |
+ - - - - - - - - - - -|- - - - - - - - - - - - - - - - - - - - - - - - - - - - - -|- - - - - - - - +
                       |                                                           |
                       v                                                           v
       +-------------------------------+                          +---------------------------------+
       |          POSTGRESQL           |                          |       CLOUDFLARE R2 BUCKET      |
       |     `terra-prod-postgres`     |                          |   (S3-Compatible Object Store)  |
       |  - DB: `terra_core`           |                          | - Prefix `core/` (Assessments)  |
       |  - DB: `terra_ghs`            |                          | - Prefix `ghs/`  (Rasters/Zarr) |
       +-------------------------------+                          +---------------------------------+
```

### Component Topology & Port Allocation

| Component | Image / Base | Internal Address | Host Port (Dev) | Host Port (Prod) | Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CORE API** | `terra-core` (Python 3.13) | `http://core:8000` | `127.0.0.1:8000` | `127.0.0.1:8000` | Public Application Gateway & REST API |
| **CORE WORKER** | `terra-core` (Python 3.13) | None | None | None | Async Scientific Assessment queue worker |
| **GHS API** | `terra-ghs` (Python 3.13) | `http://ghs-api:8080` | `127.0.0.1:8080` | None (Internal) | Geospatial Ingestion, Decoders & Harmonization |
| **GHS WORKER** | `terra-ghs` (Python 3.13) | None | None | None | Background Granule Ingestion & Processing |
| **FRONTEND** | `terra-frontend` (Node 22) | `http://frontend:5173`| `127.0.0.1:5173` | None (Cloudflare Pages) | Vite SPA Development Server (Dev only) |
| **POSTGRESQL** | `postgres:16-alpine` | `postgres:5432` | `127.0.0.1:5432` | None (Internal) | Multi-database engine (`terra_core` + `terra_ghs`) |
| **CLOUDFLARED**| `cloudflare/cloudflared` | None | None | None (Outbound) | Optional Zero-Trust Ingress Tunnel |

---

## 2. Local Development (`compose.dev.yaml`)

The development Compose environment completely mirrors the 5-process developer setup (`make dev-full`) with automated PostgreSQL multi-database provisioning and Alembic migrations.

### Prerequisites

- Docker Engine 24.0+ & Docker Compose v2.20+
- Host ports `5432`, `8000`, `8080`, and `5173` available.

### Quickstart

1. **Prepare Environment File:**
   ```bash
   cp deploy/containerization/.env.compose.example .env
   ```

2. **Launch All Services:**
   ```bash
   docker compose -f deploy/containerization/compose.dev.yaml up --build
   ```
   Or in detached mode:
   ```bash
   docker compose -f deploy/containerization/compose.dev.yaml up --build -d
   ```

3. **Verify Service Accessibility:**
   - **Frontend UI:** [http://localhost:5173](http://localhost:5173)
   - **Core API Health:** [http://localhost:8000/health/ready](http://localhost:8000/health/ready)
   - **GHS API Health:** [http://localhost:8080/ready](http://localhost:8080/ready)
   - **PostgreSQL Database:** `localhost:5432` (User: `postgres`, Pass: `postgres`)

4. **Inspect Container Health and Logs:**
   ```bash
   # Check container status and health checks
   docker compose -f deploy/containerization/compose.dev.yaml ps

   # Follow logs across all containers
   docker compose -f deploy/containerization/compose.dev.yaml logs -f

   # Follow specific service (e.g. Core Worker)
   docker compose -f deploy/containerization/compose.dev.yaml logs -f core-worker
   ```

5. **Graceful Shutdown (Preserving Data):**
   ```bash
   docker compose -f deploy/containerization/compose.dev.yaml down
   ```
   *(Note: Never run `docker compose down -v` unless you intentionally want to delete all local databases and downloaded geospatial caches).*

---

## 3. Production VPS Deployment (`compose.prod.yaml`)

In production, the backend runs in isolated Docker containers with hardened security policies. The frontend development server is **never** deployed to the VPS; the frontend is hosted on Cloudflare Pages.

### VPS Host Requirements

- **Operating System:** Ubuntu 22.04 LTS / 24.04 LTS or Debian 12 (bookworm).
- **Hardware:** Minimum 4 vCPU, 8 GB RAM, 50 GB NVMe storage (raster decoding and temporal re-projection are compute- and memory-intensive).
- **Software:** Docker Engine with Compose plugin (`sudo apt-get install docker-ce docker-compose-plugin`).

### Production Security Boundaries

- All backend containers execute with `ENVIRONMENT=production` and non-root users (`uid 10001: terra`, `uid 999: ghs`).
- `DEBUG=false` is enforced.
- Development authentication endpoint (`POST /api/v1/auth/dev-session`) is strictly disabled by Core when `ENVIRONMENT=production`.
- PostgreSQL, GHS API, and Workers have **no published host ports** and cannot be reached from the internet.
- Core API listens only on `127.0.0.1:8000` (or connects outbound through Cloudflare Tunnel), preventing unauthenticated direct port exposure.
- Persistent volumes are isolated by function: database data, Core scientific artifacts, GHS storage, and temporary scratch space.

### Production Environment Setup

1. **Clone repository and create production env file:**
   ```bash
   git clone https://github.com/ashfromsky/project-terra.git /opt/project-terra
   cd /opt/project-terra

   # Create production environment file outside git
   cp deploy/containerization/.env.compose.example deploy/containerization/.env.prod
   chmod 600 deploy/containerization/.env.prod
   ```

2. **Generate Cryptographic Secrets:**
   ```bash
   # Generate PostgreSQL password
   POSTGRES_PWD=$(openssl rand -hex 24)

   # Generate Core JWT Secret Key (>= 32 chars)
   JWT_SECRET=$(openssl rand -hex 32)

   # Generate GHS Admin Token
   GHS_TOKEN=$(openssl rand -hex 32)

   echo "POSTGRES_PASSWORD=${POSTGRES_PWD}"
   echo "JWT_SECRET_KEY=${JWT_SECRET}"
   echo "GHS_ADMIN_TOKEN=${GHS_TOKEN}"
   ```
   Paste these generated values into `deploy/containerization/.env.prod`.

3. **Configure Domain & OAuth Settings in `.env.prod`:**
   ```dotenv
   ENVIRONMENT=production
   DEBUG=false

   # Domain Configuration (Same-site hierarchy)
   FRONTEND_AUTH_REDIRECT_URL=https://app.example.com/explore
   CORS_ORIGINS=["https://app.example.com"]
   AUTH_COOKIE_SECURE=true

   # GitHub OAuth
   GITHUB_CLIENT_ID=your_github_client_id
   GITHUB_CLIENT_SECRET=your_github_client_secret
   GITHUB_REDIRECT_URI=https://api.example.com/api/v1/auth/github/callback

   # Cloudflare R2 Object Storage
   STORAGE_BACKEND=s3
   S3_BUCKET=terra-production-data
   S3_ENDPOINT_URL=https://<YOUR_CF_ACCOUNT_ID>.r2.cloudflarestorage.com
   S3_REGION=auto
   AWS_ACCESS_KEY_ID=your_r2_access_key_id
   AWS_SECRET_ACCESS_KEY=your_r2_secret_access_key

   # NASA Earthdata Token (Required for live granule ingestion)
   EARTHDATA_TOKEN=your_earthdata_bearer_token
   ```

### Production Database Initialization & Migrations

Database initialization behaves differently between Core and GHS:

1. **GHS Migrations:** GHS uses Alembic. In both dev and prod, `ghs-migration` runs `alembic upgrade head` before GHS API and GHS Worker start (`condition: service_completed_successfully`).
2. **Core Database Initialization:** Core uses SQLAlchemy `create_all` during non-production runs. In `ENVIRONMENT=production`, Core explicitly disables automatic table creation (`database_auto_create_tables` is ignored when `environment == "production"`) and Core does not yet feature Alembic migrations.

> [!IMPORTANT]
> **Core Production Database Bootstrap Step:**
> On a brand-new production database, initialize the Core schema once before launching the full daemon stack:
> ```bash
> docker compose --env-file deploy/containerization/.env.prod \
>   -f deploy/containerization/compose.prod.yaml \
>   run --rm -e ENVIRONMENT=development core \
>   python -c "import asyncio; from terra.config import get_settings; from terra.infrastructure.database import DatabaseManager; asyncio.run(DatabaseManager(get_settings()).create_schema())"
> ```
> This creates the necessary Core tables (`users`, `regions`, `assessments`, `assessment_jobs`, etc.) without altering production volume data.

### Starting Production Services

```bash
# Build and start all backend services in detached mode
docker compose --env-file deploy/containerization/.env.prod \
  -f deploy/containerization/compose.prod.yaml \
  up --build -d

# Verify all services are healthy
docker compose --env-file deploy/containerization/.env.prod \
  -f deploy/containerization/compose.prod.yaml \
  ps
```

### Verifying Service Readiness

```bash
# Verify Core API readiness (checks PostgreSQL connection & storage backend)
curl -fsS http://127.0.0.1:8000/health/ready

# Check system info endpoint
curl -fsS http://127.0.0.1:8000/api/v1/system/info
```

### Updating the Production Deployment

When pulling new code from git:
```bash
cd /opt/project-terra
git pull origin main

# Rebuild images and restart containers with zero volume loss
docker compose --env-file deploy/containerization/.env.prod \
  -f deploy/containerization/compose.prod.yaml \
  up --build -d
```

### Backup and Disaster Recovery

**Database Backup:**
```bash
docker exec terra-prod-postgres pg_dump -U postgres terra_core > /backup/terra_core_$(date +%F).sql
docker exec terra-prod-postgres pg_dump -U postgres terra_ghs > /backup/terra_ghs_$(date +%F).sql
```

**Database Restore:**
```bash
docker exec -i terra-prod-postgres psql -U postgres -d terra_core < /backup/terra_core_2026-11-15.sql
docker exec -i terra-prod-postgres psql -U postgres -d terra_ghs < /backup/terra_ghs_2026-11-15.sql
```

---

## 4. Optional Cloudflare Tunnel Ingress

Instead of exposing VPS ports `80`/`443` or managing Let's Encrypt certificates manually, Cloudflare Tunnel (`cloudflared`) creates encrypted outbound-only tunnels directly to the Cloudflare Edge.

### Setup Instructions

1. In the **Cloudflare Zero Trust Dashboard**, navigate to **Networks -> Tunnels -> Create a Tunnel**.
2. Name the tunnel (e.g. `terra-api-tunnel`).
3. Select **Docker** environment and copy the generated Tunnel Token.
4. In the Public Hostname tab, configure:
   - **Subdomain:** `api`
   - **Domain:** `example.com`
   - **Service Type:** `HTTP`
   - **URL:** `core:8000` *(Internal Docker service name and port)*
5. Add the tunnel token to your `.env.prod`:
   ```dotenv
   CLOUDFLARE_TUNNEL_TOKEN=your_copied_tunnel_token
   ```
6. Start the production Compose stack with the `tunnel` profile enabled:
   ```bash
   docker compose --env-file deploy/containerization/.env.prod \
     -f deploy/containerization/compose.prod.yaml \
     --profile tunnel up -d
   ```

Now `https://api.example.com` routes through Cloudflare's DDoS protection directly to `core:8000` with **zero** inbound firewall ports opened on your VPS.

---

## 5. Cloudflare Pages — Frontend Deployment

The React 19 / Vite frontend SPA compiles and deploys independently via Cloudflare Pages Git integration.

### Build Architecture & Prerequisite Handling

The frontend build requires generating TypeScript OpenAPI contracts directly from the backend Core Python code via `generate-contracts.mjs`.

To enable this seamlessly within Cloudflare Pages, a standalone build pipeline script is provided:
`deploy/containerization/cloudflare-pages-build.sh`

The script:
1. Validates the build environment.
2. Ensures **pnpm 12.19.0** is activated via Corepack.
3. Automatically provisions **Python 3.13** via `uv python install 3.13`.
4. Synchronizes `backend/core` dependencies via `uv sync --locked --no-dev`.
5. Executes `pnpm contracts:generate` to produce `schema.d.ts` and `openapi.json`.
6. Executes `pnpm build` (`tsc -b && vite build`) to produce `frontend/dist/`.
7. Generates a Cloudflare Pages `_redirects` file (`/* /index.html 200`) to ensure browser refresh and direct URL navigation function properly for client-side routing (`/explore`, `/assessments`, etc.).

### Cloudflare Pages Dashboard Configuration

Create a new Cloudflare Pages project connected to your GitHub repository:

| Setting | Value |
| :--- | :--- |
| **Project Name** | `project-terra` |
| **Production Branch** | `main` |
| **Framework Preset** | `None` |
| **Root Directory** | `/` *(Repository Root)* |
| **Build Command** | `bash deploy/containerization/cloudflare-pages-build.sh` |
| **Build Output Directory** | `frontend/dist` |

### Pages Environment Variables

Under **Settings -> Environment variables**, configure:

| Variable | Environment | Example Value | Description |
| :--- | :--- | :--- | :--- |
| `VITE_API_BASE_URL` | Production | `https://api.example.com` | Absolute HTTPS address of Core API |
| `VITE_API_BASE_URL` | Preview | `https://api-staging.example.com` | Staging API URL for PR preview deployments |
| `VITE_NASA_GIBS_BASE_URL` | All | `https://gibs.earthdata.nasa.gov` | NASA GIBS tile imagery endpoint |
| `FRONTEND_DIST_DIR` | Production VPS | `/app/web` | Built SPA directory served by Core at the API origin. The Core Docker image builds it automatically. |

### Same-origin SPA hosting (VPS)

The production Core image includes a built copy of `frontend/dist` and sets
`FRONTEND_DIST_DIR=/app/web`. Core serves the SPA at `/` and non-API routes,
while `/api/v1/*`, `/health*`, `/docs`, and `/openapi.json` keep their API
behavior. This makes the frontend available at the public API origin without a
separate Pages deployment or CORS configuration.

> [!NOTE]
> Cloudflare Pages remains an optional target. Its workflow step requires the
> `CLOUDFLARE_API_TOKEN` repository secret; without it, Pages is skipped and the
> VPS-hosted same-origin frontend remains the current deployment.

> [!CAUTION]
> **No Secrets in Frontend:** Never configure `JWT_SECRET_KEY`, `GITHUB_CLIENT_SECRET`, `EARTHDATA_TOKEN`, `POSTGRES_PASSWORD`, or R2 access keys in Cloudflare Pages. Frontend code is compiled into public client bundles.

---

## 6. Cloudflare R2 — Object Storage Integration

PROJECT TERRA uses Cloudflare R2 via its S3-compatible SigV4 API for persistent storage of large rasters, derived COGs, and assessment artifacts.

### Bucket Creation & Prefix Separation

Create a single private R2 bucket (e.g. `terra-data`).

Core and GHS share this bucket cleanly through isolated key prefixes:
- **Core:** `core/assessments/<assessment_id>/result.json`, `provenance.json`
- **GHS Raw Zone:** `raw/<provider>/<year>/<granule_id>`
- **GHS Intermediate Zone:** `intermediate/<job_id>/`
- **GHS Derived Zone:** `derived/<dataset_id>/<filename>.tif`

### Cloudflare R2 CORS Configuration

To allow authenticated browser downloads of exported assessment bundles via presigned URLs, configure CORS on the R2 bucket:

In **Cloudflare Dashboard -> R2 -> [bucket-name] -> Settings -> CORS Policy**:
```json
[
  {
    "AllowedOrigins": [
      "https://app.example.com"
    ],
    "AllowedMethods": [
      "GET",
      "HEAD"
    ],
    "AllowedHeaders": [
      "*"
    ],
    "ExposeHeaders": [
      "ETag",
      "Content-Type",
      "Content-Disposition"
    ],
    "MaxAgeSeconds": 3600
  }
]
```

### Object Storage vs Scratch Storage Separation

- **Cloudflare R2 (`STORAGE_BACKEND=s3`):** Used exclusively for persistent data products (ingested rasters, standardized temporal datasets, scientific assessment JSON, and SHA-256 provenance manifests).
- **Scratch Filesystem (`/data/ghs_scratch`):** Managed by GHS `StorageZoneManager` on local volume `prod_ghs_scratch` for intermediate GeoTIFF warping, HDF/NetCDF decoding, and tile slicing. Stale scratch data is purged automatically.

---

## 7. Domain & Authentication Architecture

PROJECT TERRA uses **HttpOnly session cookies** (`AUTH_COOKIE_NAME=terra_session`) for authenticated state.

### Same-Site Custom Domain Recommendation

To ensure cookies are handled smoothly without third-party cookie restrictions, deploy the frontend and backend under the same registrable domain:
- **Frontend SPA:** `https://app.example.com` (Cloudflare Pages)
- **Backend API:** `https://api.example.com` (VPS via Tunnel or Reverse Proxy)

Under this topology:
- Cookie policy: `SameSite=Lax`, `Secure=true`, `HttpOnly=true`.
- The frontend and backend share the parent registrable domain (`example.com`).
- Browser requests to `https://api.example.com/api/v1/*` include the session cookie automatically via `credentials: 'include'`.

### GitHub OAuth Flow Across Domains

1. User clicks **Sign In with GitHub** on `https://app.example.com`.
2. Frontend redirects user to `https://api.example.com/api/v1/auth/github/login`.
3. Core sets an OAuth state cookie and redirects to GitHub.
4. User authorizes; GitHub redirects back to `GITHUB_REDIRECT_URI`:
   `https://api.example.com/api/v1/auth/github/callback?code=...&state=...`
5. Core exchanges the authorization code with GitHub for user credentials.
6. Core sets the HttpOnly `terra_session` cookie on response.
7. Core redirects user to `FRONTEND_AUTH_REDIRECT_URL`:
   `https://app.example.com/explore`
8. Frontend loads; `useCurrentUser()` queries `/api/v1/auth/me` with cookie credentials, successfully restoring the session.

---

## 8. Verification & Operational Health Checks

Validate Compose definitions and build scripts at any time:

```bash
# 1. Validate Development Compose configuration syntax
docker compose -f deploy/containerization/compose.dev.yaml config --quiet

# 2. Validate Production Compose configuration syntax (providing sample prod secrets)
POSTGRES_PASSWORD=test_postgres_pass \
JWT_SECRET_KEY=test_jwt_secret_key_at_least_32_characters \
CORS_ORIGINS='["https://app.example.com"]' \
FRONTEND_AUTH_REDIRECT_URL=https://app.example.com/explore \
GITHUB_REDIRECT_URI=https://api.example.com/api/v1/auth/github/callback \
docker compose -f deploy/containerization/compose.prod.yaml config --quiet

# 3. Test Cloudflare Pages Build Script locally
bash deploy/containerization/cloudflare-pages-build.sh
```
