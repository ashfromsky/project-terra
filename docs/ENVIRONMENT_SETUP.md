# PROJECT TERRA — Environment Setup & Runtime Operations

This guide covers configuring, validating, and running the complete five-process PROJECT TERRA development stack from the repository root.

---

## 1. Prerequisites

- **Node.js 20+** and **pnpm** (frontend SPA & development orchestrator)
- **Python 3.13+** and **uv** (`backend/core`, `backend/scientific`, `backend/worker`, `backend/services/geospatial_harmonization`)
- Optional external credentials for live restricted NASA DAAC downloads and GitHub OAuth (see Section 4)

---

## 2. Service Addresses & Architecture Topology

All local development presets share one consistent addressing contract:

| Process | Role | Local Address / Port | Health Probe |
|---|---|---|---|
| `FRONTEND` | Vite + React 19 SPA | `http://localhost:5173` | `http://localhost:5173` |
| `CORE` | `terra-core` FastAPI API (`auth`, `layers`, `regions`, `data_sources`, `assessments`) | `http://127.0.0.1:8000` | `http://127.0.0.1:8000/health` |
| `CORE-WORKER` | `terra-worker` async Scientific Assessment queue runner | Background process (no HTTP listener) | Polls Core `DATABASE_URL` |
| `GHS` | Geospatial Harmonization Service FastAPI API (ADR-0002) | `http://127.0.0.1:8080` | `http://127.0.0.1:8080/health` |
| `GHS-WORKER` | GHS `WorkerRunner` ingestion & harmonization queue runner | Background process (no HTTP listener) | Polls `GHS_DATABASE_URL` |

Core API communicates with GHS exclusively over HTTP (`GHS_BASE_URL`, default `http://127.0.0.1:8080`). `FRONTEND` proxies `/api` and `/health` through Vite to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`) so `HttpOnly` session cookies work seamlessly on the same origin in development.

---

## 3. Database & Storage Isolation

Because `CORE`, `CORE-WORKER`, `GHS`, and `GHS-WORKER` launch from different package directories, SQLite URLs resolve to absolute paths inside `<repo>/.data/` by default when omitted from `.env`:

- **Core Database (`DATABASE_URL`):** Shared between `CORE` API and `CORE-WORKER`.
  - Default in development / `make dev-full`: `sqlite+aiosqlite:////<repo>/.data/terra.db`
- **GHS Database (`GHS_DATABASE_URL`):** Shared between `GHS` API and `GHS-WORKER`, kept strictly independent from Core's `DATABASE_URL`.
  - Default in `make dev-full`: `sqlite+aiosqlite:////<repo>/.data/ghs.db`
  - Standalone GHS execution supports `GHS_DATABASE_URL` (preferred) with backwards-compatible fallback to `DATABASE_URL` (`sqlite+aiosqlite:///./ghs.db` when unset).
- **Local Filesystem Storage:**
  - `SCIENTIFIC_ARTIFACT_DIR` defaults to `<repo>/.data/artifacts`
  - `LOCAL_STORAGE_DIR` defaults to `<repo>/.data/ghs_storage` (`STORAGE_BACKEND=local`)

Never point `DATABASE_URL` and `GHS_DATABASE_URL` to the same SQLite file or database schema.

---

## 4. Environment Variables & Credentials

Create your local `.env` from the template:

```bash
cp .env.example .env
```

`.env` files are gitignored per ADR-0001 and must **never** be committed.

### Minimum Setup for Full Local Operation

For local exploration, **NASA POWER** ingestion, queued **GHS** processing, **Core Worker** assessments, comparison, and report exports, default values in `.env.example` work out of the box once copied to `.env`:

- **Development Auth (`POST /api/v1/auth/dev-session`):** When `ENVIRONMENT=development`, the UI exposes a one-click **Start Dev Session** button (in the top navigation bar, `/explore` AOI inspector, and authenticated workspace pages) without requiring GitHub OAuth credentials. This route is disabled (`403`) outside `ENVIRONMENT=development`.
- **GitHub OAuth (optional in development, required for OAuth flow):** Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`, and configure `GITHUB_REDIRECT_URI=http://localhost:5173/api/v1/auth/github/callback`.
- **JWT Signing Key (`JWT_SECRET_KEY`):** Defaults to a development key; replace with `openssl rand -hex 32` before any non-local deployment.

### External NASA Earthdata Credentials (for Protected DAAC Granules)

- **No credentials needed:** `nasa_power` (`POWER_DAILY`, `POWER_HOURLY`), NASA CMR metadata discovery (`POST /api/v1/data-sources/discover`), and NASA GIBS map browse tiles.
- **Earthdata Login Token required (`EARTHDATA_TOKEN`):** Needed to download protected HDF4/HDF5/NetCDF4 granules for **MODIS** (`MOD13Q1.061`, `MOD11A2.061`), **GPM IMERG** (`GPM_3IMERGHH.07/.06`), and **SMAP** (`SPL3SMP_E.006`).
  1. Register or sign in at `https://urs.earthdata.nasa.gov/`.
  2. Authorize the NASA Earthdata Cloud / LP DAAC / GES DISC / NSIDC applications on your URS profile.
  3. Generate a Bearer token at `https://urs.earthdata.nasa.gov/user_tokens`.
  4. Set `EARTHDATA_TOKEN=<your_token>` in `.env`.

### Optional S3 / Cloudflare R2 Storage (`STORAGE_BACKEND=s3`)

Keep `STORAGE_BACKEND=local` for local workflows. To test remote S3/R2 storage, set `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`.

---

## 5. Installing Dependencies, Validating & Starting

### 1. Install dependencies across all workspaces

```bash
make install
```

### 2. Run diagnostics (`make doctor`)

```bash
make doctor
```

`make doctor` verifies (without printing secret values):

- Required CLIs (`node`, `pnpm`, `uv`, `python3`)
- `.env` and `.env.example` presence
- Core `DATABASE_URL` vs `GHS_DATABASE_URL` separation and writable directories
- Consistent `GHS_BASE_URL` addressing (`http://127.0.0.1:8080`)
- Writable artifact (`SCIENTIFIC_ARTIFACT_DIR`) and storage (`LOCAL_STORAGE_DIR`) directories
- Port availability (or active TERRA health responses) on `8000`, `8080`, and `5173`
- Worker module imports (`terra_worker` and `geospatial_harmonization.worker`)
- Readiness of `EARTHDATA_TOKEN`, GitHub OAuth credentials, and storage configuration

### 3. Start the complete 5-process stack

```bash
make dev-full
```

`scripts/dev.mjs dev-full` regenerates OpenAPI TypeScript contracts, starts `CORE` and `GHS`, waits for HTTP readiness (`/health`), starts `CORE-WORKER` and `GHS-WORKER`, then starts `FRONTEND`, with prefixed logs (`[CORE]`, `[CORE-WORKER]`, `[GHS]`, `[GHS-WORKER]`, `[FRONTEND]`) and clean process-group shutdown on `Ctrl+C`.

Additional independent commands:

- `make dev` — contracts + `CORE`, `CORE-WORKER`, `FRONTEND`
- `make dev-ghs` — `GHS` API + `GHS-WORKER`
- `make dev-check` — orchestrator unit tests
- `make test` / `make ghs-test` / `make lint` / `make ghs-lint`
