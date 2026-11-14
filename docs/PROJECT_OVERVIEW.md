# PROJECT TERRA — Global Project Overview & Current State

> **Living Document Mandate:** This file is the repository-level source of truth for the global state of `PROJECT TERRA`. Per [AGENTS.md](../AGENTS.md), agents MUST read this document before non-trivial tasks and update it whenever global changes alter active services, module boundaries, data/API integration, mock status, or verification tooling.

**Baseline Snapshot:** `main` @ `9b97886` (`2026-11-14`, through PR #3)

## 1. Mission & Non-Negotiable Principles

**PROJECT TERRA** is an open-source environmental analysis platform for investigating ecosystem response, environmental stress (such as drought), and resilience dynamics using NASA Earth observation products and hydrometeorological context (initiated in the context of NASA Space Apps Challenge 2026; independent project, not an official NASA product).

Core engineering and scientific invariants:

- **Scientific correctness & provenance:** Preserve product versions, native spatial/temporal grids, units, QA flags, missing-observation accounting, and data lineage. Never fabricate formulas, weights, or measurements.
- **Visualization vs. analysis boundary:** NASA GIBS tile layers are strictly for contextual map visualization; quantitative statistics and time series must be computed from decoded scientific products.
- **Strict architectural layering:** Keep scientific calculations independent of HTTP, database, and UI code. Keep API handlers thin and React components free of scientific math.
- **Honest UI states:** Clearly mark synthetic/demonstration data (`SYNTHETIC DATA`), experimental metrics (such as TRI), and unavailable backend capabilities.

---

## 2. Global Topology: Target Architecture vs. Current Reality

[SYSTEM_ARCHITECTURE.md](./architecture/SYSTEM_ARCHITECTURE.md) specifies a **Modular Monolith** (`backend/core/` + shared `backend/worker/` + `backend/scientific/`) backed by PostgreSQL/PostGIS, S3 Data Lake, DuckDB, TiTiler, and Caddy.

Currently, the repository contains **three disconnected runtime islands** and **two empty placeholder packages**:

```text
project-terra/
├── frontend/                                 # React 19 / Vite 8 / MapLibre 5 / deck.gl 9 / d3-geo SPA
│   └── only calls GET /health; map & analytics use MockMapDataProvider (isConnectedBackend = false)
├── backend/
│   ├── core/                                 # terra-core FastAPI API (Auth, Regions JSON CRUD, 16 static Layers)
│   ├── services/geospatial_harmonization/    # ADR-0002 isolated service (API + WorkerRunner + S3/Local + Alembic)
│   ├── scientific/                           # .gitkeep only (not yet implemented)
│   └── worker/                               # .gitkeep only (not yet implemented)
└── docs/
    ├── PROJECT_OVERVIEW.md                   # This living global state summary
    ├── architecture/SYSTEM_ARCHITECTURE.md   # Target architecture baseline
    └── adr/                                  # ADR-0001 (stack) & ADR-0002 (GHS service boundary)
```

---

## 3. Component Readiness Matrix

| Component | Location | Status | Implemented Capabilities & Actual Gaps |
| :--- | :--- | :--- | :--- |
| **Frontend SPA** | `frontend/` | **Partially implemented** | FSD-lite (`app -> pages -> widgets -> features -> entities -> shared`). 7 routes (`/`, `/overview`, `/explore`, `/comparative-analysis`, `/assessments`, `/reports`, `/data-sources`). PR #2 added `Project Terra` title, favicon, and logo (`frontend/assets/terra-logo.png` in `TopNavigation`). `/explore` implements Equal Earth (`d3-geo`), Globe & Mercator (`MapLibre GL JS 5`), `deck.gl`, NASA GIBS browse layers, AOI drawing/GeoJSON export, and the 16-layer catalog UI. **Gaps:** `defaultMapDataProvider` is `MockMapDataProvider` (`isConnectedBackend = false`); `TopNavigation` hardcodes `"Researcher"` with no GitHub login/logout UX; only `/health` is fetched (`src/shared/api/health.ts`); `/overview`, `/assessments`, `/reports`, `/comparative-analysis`, `/data-sources` display `SYNTHETIC DATA` / `Example data` placeholders (`TERRA-SYN-2026-01`, synthetic Caatinga/Cerrado, illustrative `30/35/20/15%` TRI weights). |
| **Core Backend API** | `backend/core/` | **Implemented (foundation)** | `terra-core` (`0.1.0`, Python `>=3.13`, FastAPI, Granian, SQLAlchemy asyncio, Pydantic Settings, PyJWT, HTTPX, `asyncpg`/`aiosqlite`). Routes: `/health`, `/health/live`, `/health/ready`, `/api/v1/health`, `/api/v1/system/info`, `/api/v1/auth/github/{login,callback}`, `/api/v1/auth/{logout,me}`, `/api/v1/regions*` (WGS 84 GeoJSON validation + pure-Python spherical area, JSON storage without PostGIS), `/api/v1/layers*` (static 16-layer catalog returning `availableSteps: 0`). Schema auto-created in non-production (`Base.metadata.create_all`; no Alembic). **Gaps:** No `analyses`, `assessments`, `comparisons`, `reports`, `ai_analyst`, or GHS integration. |
| **Geospatial Harmonization Service (GHS)** | `backend/services/geospatial_harmonization/` | **Implemented (isolated)** | Added in PR #3 per `docs/adr/0002-geospatial-harmonization-service.md`. Separate FastAPI + Granian app, `Dockerfile`, Alembic (`ghs_datasets`, `ghs_assets`, `ghs_harmonization_jobs`), `WorkerRunner` (`FOR UPDATE SKIP LOCKED` on PostgreSQL, SQLite fallback), `LocalObjectStore` & `S3ObjectStore` (`boto3`). Endpoints: `/health`, `/ready`, `/api/v1/health`, `/api/v1/ready`, `/api/v1/capabilities`, `POST/GET /api/v1/jobs` (`202 Accepted`), `POST /api/v1/harmonize`, `GET /api/v1/datasets*`. **Gaps:** Retrieval uses NASA CMR / `granule_url` (AppEEARS & Harmony clients are not yet implemented); `integrate_rate_to_depth` and `aggregate_temporal_stack` in `transformations/temporal.py` are not yet wired into `HarmonizationService.execute_plan`; service is completely disconnected from `backend/core/` and `frontend/`. |
| **Scientific Core** | `backend/scientific/` | **Not implemented** | `.gitkeep` only. Missing seasonal baselines/anomalies, Mann–Kendall, Sen's slope, autocorrelation/multiple-testing corrections, Resistance/Recovery/Stability/Sensitivity, and validated TRI. |
| **Shared Core Worker** | `backend/worker/` | **Not implemented** | `.gitkeep` only. Async queue execution currently exists solely for harmonization jobs inside `geospatial_harmonization`. |
| **Infra, Analytics & CI** | Root / deployment | **Not implemented** | No PostGIS spatial queries in runtime, no DuckDB analytics pipeline, no TiTiler COG tile service, no Caddy config, and no `.github/workflows/` CI. |

---

## 4. Data Products & Scientific Catalog Snapshot

- **Layer Catalog (`16` static layers in both `frontend` and `backend/core`):**
  - *Observation (`6`):* `ndvi-mod13q1`, `evi-mod13q1`, `lst-mod11a2`, `lst-anomaly`, `precip-gpm-imerg`, `soil-moisture-smap`.
  - *Derived (`5`):* `ndvi-anomaly`, `evi-anomaly`, `vegetation-trend`, `mann-kendall-significance`, `sens-slope` (algorithms unimplemented).
  - *Resilience (`5`):* `resistance`, `recovery`, `stability`, `sensitivity`, `experimental-tri` (algorithms and weights unvalidated).
- **GHS Handlers & Decoders (`backend/services/geospatial_harmonization/`):**
  - *Handlers:* `MODISHandler` (`MOD13Q1.061`, `MOD11A2.061`), `GPMIMERGHandler` (`GPM_3IMERGHH.07/.06`, `Early`/`Late`), `SMAPHandler` (`SPL3SMP_E.006`), `NASAPowerHandler` (`nasa_power`, `power_daily`, `power_hourly`), and SSRF-guarded `GenericHandler` (disabled when `generic_handler_allowed_hosts` is empty).
  - *Format Readers (`ReaderRegistry`):* `GeoTIFF`, `HDF4`, `HDF5`, `NetCDF`, `Zarr`, `JSON`, `CSV`.
  - *Transformations:* `TargetGridTransformer` (Rasterio/GDAL warp, center-to-corner affine) and `QualityValidator`.

---

## 5. Tooling, Verification Baseline & Repo Quirks

- **Build automation:** Root [Makefile](../Makefile) defines `frontend-*` (`npm`) and `backend-*` (`backend/core` via `uv`) targets; `geospatial_harmonization` commands currently live only in its service README.
- **Lockfile & asset notes:** `frontend/` has tracked `package-lock.json` alongside untracked `pnpm-lock.yaml` / `pnpm-workspace.yaml` (requires standardization). `frontend/index.html` references `/assets/terra-logo.png`, rewritten by Vite during build from `frontend/assets/terra-logo.png` (no `frontend/public/assets/` directory exists).
- **Observed verification on `9b97886` (`2026-11-14`):**
  - `frontend`: `npm run typecheck && npm run lint && npm run build` passes (`tsc -b`, `eslint .`, `vite build` 1144 modules; chunk-size warning on `dist/assets/index-*.js` at `2,121.58 kB`).
  - `backend/core`: `uv run pytest` (`42 passed`, `1` Starlette `httpx2` warning), `uv run ruff check .`, and `uv run ruff format --check .` pass.
  - `backend/services/geospatial_harmonization`: `uv run pytest` (`79 passed, 1 skipped` — `tests/integration/test_postgres_locking.py` skips unless `GHS_TEST_POSTGRES_URL` is set), `ruff check`, `ruff format --check`, and `mypy src` (`strict`, `52` source files) pass.

---

## 6. Next Integration Priorities & Reference Map

1. **P0 — Connect UI ↔ `backend/core`:** Integrate GitHub Auth UX, Regions persistence, and Layer Catalog API into `frontend/`, retiring `MockMapDataProvider` cleanly as real endpoints go live.
2. **P0/P1 — Connect `backend/core` ↔ GHS & complete temporal pipeline:** Define the orchestration/RPC contract between `terra-core` and `geospatial_harmonization`, wire `temporal.py` into `HarmonizationService.execute_plan`, evaluate AppEEARS/Harmony needs, and verify `SKIP LOCKED` against PostgreSQL.
3. **Sync documentation & CI:** Update [SYSTEM_ARCHITECTURE.md](./architecture/SYSTEM_ARCHITECTURE.md) (GitHub OAuth baseline + ADR-0002), update [README.md](../README.md) checklist, clean up frontend lockfiles, and add `.github/workflows/` CI.
4. **P1–P2 — Implement `backend/scientific/` & reference AOI flow:** Select benchmark AOIs/drought event and implement validated anomaly, trend, and resilience algorithms before removing synthetic UI placeholders.

**Authoritative Documents:** [AGENTS.md](../AGENTS.md) · [SYSTEM_ARCHITECTURE.md](./architecture/SYSTEM_ARCHITECTURE.md) · [ADR-0001](./adr/0001-bootstrap-stack.md) · [ADR-0002](./adr/0002-geospatial-harmonization-service.md) · [frontend/DESIGN.md](../frontend/DESIGN.md)
