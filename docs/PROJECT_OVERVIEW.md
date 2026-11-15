# PROJECT TERRA — Global Project Overview & Current State

> **Living Document Mandate:** This file is the repository-level source of truth for the global state of `PROJECT TERRA`. Per [AGENTS.md](../AGENTS.md), agents MUST read this document before non-trivial tasks and update it whenever global changes alter active services, module boundaries, data/API integration, mock status, or verification tooling.

**Baseline Snapshot:** `feat/integration-scientific-ci` (built atop `main`, `2026-11-15`)

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

Currently, `frontend/` connects to `backend/core/` through generated OpenAPI TypeScript contracts (single source of truth), `backend/core/` integrates `backend/scientific/` (`terra-scientific`) for deterministic Scientific Assessments and fetches prepared datasets over HTTP from `backend/services/geospatial_harmonization/` (GHS), while `backend/worker/` executes queued Core assessments asynchronously (`claim_next_queued()`):

```text
project-terra/
├── frontend/                                 # React 19 / Vite 8 / MapLibre 5 / deck.gl 9 / d3-geo SPA (pnpm)
│   └── src/shared/api/generated/             # auto-generated openapi.json + schema.d.ts (openapi-fetch)
├── backend/
│   ├── core/                                 # terra-core FastAPI API (System, GitHub Auth, Regions CRUD, 16 Layers, Assessments)
│   ├── scientific/                           # terra-scientific P0+P1 pure Python Scientific Core package (P2 deferred)
│   ├── worker/                               # terra-worker async Scientific Assessment queue runner (polls Core DB + fetches GHS)
│   └── services/geospatial_harmonization/    # ADR-0002 isolated service (API + WorkerRunner + S3/Local + Alembic)
└── docs/
    ├── PROJECT_OVERVIEW.md                   # This living global state summary
    ├── architecture/SYSTEM_ARCHITECTURE.md   # Target architecture baseline
    ├── scientific/SCIENTIFIC_CORE.md         # Scientific Core methods, data contracts, QA rules, & P0/P1/P2 status
    └── adr/                                  # ADR-0001 (stack) & ADR-0002 (GHS service boundary)
```

---

## 3. Component Readiness Matrix

| Component | Location | Status | Implemented Capabilities & Actual Gaps |
| :--- | :--- | :--- | :--- |
| **Frontend SPA** | `frontend/` | **Connected to Core API (Assessments & Data Sources integrated; 3 analytical pages still synthetic)** | FSD-lite (`app -> pages -> widgets -> features -> entities -> shared`). 7 routes (`/`, `/overview`, `/explore`, `/comparative-analysis`, `/assessments`, `/reports`, `/data-sources`). Vite dev proxy routes `/api` and `/health` to `backend/core`. `TopNavigation` integrates `/api/v1/auth/*` and `/api/v1/system/info`. `/explore` integrates `/api/v1/layers*`, Equal Earth / Globe / Mercator + NASA GIBS browse imagery, and `/api/v1/regions*` AOI CRUD. `/assessments` integrates `GET /api/v1/assessments/methods`, `POST /api/v1/assessments`, `GET /api/v1/assessments`, `GET /api/v1/assessments/{id}`, and `POST /api/v1/assessments/{id}/execute` (rendering separated resilience dimensions, negative-peak event resistance traceability, quality reports, uncertainty, provenance, and `queued`/`running`/`completed`/`completed_partial`/`insufficient_data`/`failed`/unauthenticated states). `/data-sources` integrates `/health`, `/api/v1/system/info`, `/api/v1/layers`, and authenticated assessment provenance while explicitly reporting GHS discovery/jobs endpoints as unavailable in Core `/api/v1` (ADR-0002). **Gaps:** `/overview`, `/reports`, and `/comparative-analysis` still display `SYNTHETIC DATA` / `Example data` placeholders. |
| **Core Backend API** | `backend/core/` | **Implemented (P0 + Scientific Integration)** | `terra-core` (`0.1.0`, Python `>=3.13`, FastAPI, Granian, SQLAlchemy asyncio, Pydantic Settings reading root `../../.env` and `.env`, PyJWT, HTTPX, `asyncpg`/`aiosqlite` with default dev SQLite fallback). Keeps Core lightweight (no GDAL/rasterio dependencies) by delegating numerical runs to `terra-scientific` off the event loop (`asyncio.to_thread`) and fetching prepared metadata from GHS via `HttpxGhsDatasetClient`. Routes: `/health`, `/health/live`, `/health/ready`, `/api/v1/health`, `/api/v1/system/info`, `/api/v1/auth/github/{login,callback}`, `/api/v1/auth/{logout,me}`, `/api/v1/regions*` (WGS 84 GeoJSON + spherical area, JSON storage without PostGIS), `/api/v1/layers*` (16-layer catalog returning `availableSteps: 0`), `/api/v1/assessments/methods`, and authenticated `/api/v1/assessments*` (`POST` inline/GHS immediate or queued, `GET` list/detail, `POST /{id}/execute`, artifact path containment, `422` NASA GIBS rejection). **Gaps:** Schema auto-created in non-production (`Base.metadata.create_all`; no Alembic); no `comparisons`, `reports`, or `ai_analyst` endpoints; no proxy routes for GHS `/providers`, `/discover`, `/jobs`, or `/datasets`. |
| **Scientific Core** | `backend/scientific/` | **Implemented (P0 & P1; P2 deferred)** | `terra-scientific` (`0.1.0`, `numpy`, `pandas`, `pydantic`, `scipy`; optional `[geospatial]` extra for GeoTIFF). Implements source-aware QA & scale/fill policies (`MOD13Q1.061`, `MOD11A2.061`, `GPM_3IMERGHH.07/.06` half-hourly rate-to-depth `mm/hr * 0.5`, `SPL3SMP_E.006` AM/PM split, `NASA_POWER` `MERRA-2`/`CERES SYN1deg`), `NASA GIBS` quantitative rejection, intensive/extensive temporal aggregation, stratified climatologies with overlap-leakage prevention, parametric/robust/percentile anomalies, exact ($n \le 10$) + tie-corrected Mann–Kendall, Hirsch–Slack Seasonal MK, elapsed-time Sen's slope + Gilbert CI, lag-k ACF / Ljung–Box Q / ESS / opt-in Hamed–Rao & Yue–Wang TFPW, area-weighted zonal statistics, chunked pixel MK+Sen + Benjamini–Hochberg FDR, Moran's I & Getis–Ord $G_i^*$, deseasonalized cross-variable Pearson/Spearman/lag/OLS+VIF/partial correlation (with pairwise `ols_slope`, `ols_slope_se`, `ols_slope_p`, and `slope_unit`), Pettitt (1979) structural break detection, consecutive-confirmation (`confirmation_steps`) post-event recovery bounded before `next_event_idx` (returning `insufficient_data` when pre-event baseline is absent), separated Resistance (negative disturbance peaks only with `EventResistanceDetail` traceability; `unavailable` without negative shocks), scale-invariant Stability (standardized residuals), OLS-slope Sensitivity, 3-tier uncertainty, and SHA-256 provenance/JSON artifact writer (`event_recovery` & `resilience_dimensions` `1.1.0`). **Deferred (P2):** `composite_tri` (`unavailable_unvalidated`), `critical_slowing_down`, and `causal_attribution` remain `implemented=False` in `DEFAULT_METHOD_REGISTRY`. |
| **Shared Core Worker** | `backend/worker/` | **Implemented (`terra-worker`)** | Async queue runner (`AssessmentWorkerRunner`, CLI `python -m terra_worker`) claiming `queued` rows from Core DB via `claim_next_queued()` (`FOR UPDATE SKIP LOCKED` on PostgreSQL, atomic conditional update on SQLite), resolving GHS datasets via `HttpxGhsDatasetClient`, executing `ScientificAssessmentService`, persisting deterministic JSON payloads/artifacts, and isolating job failures (`status="failed"`). **Gaps:** Live PostgreSQL `SKIP LOCKED` execution requires a provisioned PostgreSQL instance (unit/integration suite tests SQLite in-memory). |
| **Geospatial Harmonization Service (GHS)** | `backend/services/geospatial_harmonization/` | **Implemented (ADR-0002 service)** | Separate FastAPI + Granian app, `Dockerfile`, Alembic (`0003_job_retry_and_idempotency`), `WorkerRunner` (`FOR UPDATE SKIP LOCKED` on PostgreSQL, SQLite fallback), `LocalObjectStore` & `S3ObjectStore`, four NASA handlers (`MODISHandler`, `GPMIMERGHandler`, `SMAPHandler`, `NASAPowerHandler`) + disabled `GenericHandler`, `TargetGridTransformer`, `QualityValidator`, storage quota/dedup/lifecycle services, and `/api/v1/{discover,jobs,harmonize,datasets,storage}` endpoints consumed by Core via `GET /api/v1/datasets/{id}`. **Gaps:** AppEEARS & Harmony task workflows are not yet implemented; `temporal.py` helpers are not yet wired into `HarmonizationService.execute_plan`; GHS→Core transport (`HttpxGhsDatasetClient`) requires `extensions.time_series` pre-populated on GHS dataset metadata rather than decoding Zarr/COG artifacts directly. |
| **API Contracts Pipeline** | `backend/core/terra/openapi_export.py` + `frontend/scripts/generate-contracts.mjs` | **Implemented** | `python -m terra.openapi_export` emits `frontend/src/shared/api/generated/openapi.json` from FastAPI in memory (zero DB required) and `openapi-typescript` generates `frontend/src/shared/api/generated/schema.d.ts` automatically on `predev`, `prebuild`, `pretypecheck`, `pretest`, and `make contracts`. `openapi-fetch` binds frontend calls strictly to `paths` and `components['schemas']`. |
| **CI/CD & Runtime Infra** | `.github/workflows/` + `Makefile` | **Offline CI & Artifact Stage Implemented; Prod Infra Not Configured** | `.github/workflows/ci.yml` runs parallel offline jobs (`backend-core`, `scientific-core`, `worker`, `ghs-offline`, `frontend-and-contracts` w/ `make dev-check`, OpenAPI contract diff check, Vite build artifact `terra-frontend-dist`, and `cd-artifact-readiness` GHS Dockerfile build check). `.github/workflows/optional-live-and-postgres.yml` provides manual dispatch for PostgreSQL `SKIP LOCKED` and live NASA checks. **Gaps:** No PostGIS spatial queries, DuckDB analytics, TiTiler COG service, Caddy config, or configured production deployment target/credentials. |

---

## 4. Data Products & Scientific Catalog Snapshot

- **Layer Catalog (`16` static layers owned by `backend/core` and exposed via `/api/v1/layers`):**
  - *Observation (`6`):* `ndvi-mod13q1`, `evi-mod13q1`, `lst-mod11a2`, `lst-anomaly`, `precip-gpm-imerg`, `soil-moisture-smap`.
  - *Derived (`5`):* `ndvi-anomaly`, `evi-anomaly`, `vegetation-trend`, `mann-kendall-significance`, `sens-slope` (corresponding algorithms are now implemented for assessments in `terra-scientific`; layer tile/step counts in `/api/v1/layers` remain static catalog metadata until connected to stored raster tiles).
  - *Resilience (`5`):* `resistance`, `recovery`, `stability`, `sensitivity`, `experimental-tri` (`resistance`, `recovery`, `stability`, and `sensitivity` metrics are computed separately in `terra-scientific`; `experimental-tri` remains withheld/`unavailable_unvalidated`).
- **Scientific Method Registry (`DEFAULT_METHOD_REGISTRY`, exposed via `/api/v1/assessments/methods`):**
  - `14` implemented P0/P1 methods and `3` explicitly deferred P2 specs (`composite_tri`, `critical_slowing_down`, `causal_attribution`).
- **GHS Handlers & Decoders (`backend/services/geospatial_harmonization/`):**
  - *Handlers:* `MODISHandler` (`MOD13Q1.061`, `MOD11A2.061`), `GPMIMERGHandler` (`GPM_3IMERGHH.07/.06`, `Early`/`Late`), `SMAPHandler` (`SPL3SMP_E.006`), `NASAPowerHandler` (`nasa_power`, `power_daily`, `power_hourly`), and SSRF-guarded `GenericHandler` (disabled when allowlist is empty).
  - *Format Readers (`ReaderRegistry`):* `GeoTIFF`, `HDF4`, `HDF5`, `NetCDF`, `Zarr`, `JSON`, `CSV`.

---

## 5. Tooling & Verification Structure

- **Build automation:** Root [Makefile](../Makefile) defines unified workflows across all components using `pnpm` (`frontend/`), `uv` (`backend/core/`, `backend/scientific/`, `backend/worker/`, `backend/services/geospatial_harmonization/`), and Node orchestration tests (`make dev-check`):
  - `make test`: runs `backend-test`, `scientific-test`, `worker-test`, and `frontend-test`.
  - `make lint`: runs `frontend-lint`, `backend-lint`, `scientific-lint` (`ruff` + strict `mypy`), and `worker-lint` (`ruff` + strict `mypy`).
  - `make ghs-test` / `make ghs-lint`: runs GHS test suite (PostgreSQL `SKIP LOCKED` skips unless `GHS_TEST_POSTGRES_URL` is set; live NASA smoke tests skip unless `RUN_LIVE_NASA_TESTS=1`) and Ruff + strict `mypy`.
  - `make contracts` / `make frontend-typecheck` / `make frontend-build`: regenerates OpenAPI TypeScript contracts and verifies strict TypeScript + Vite production build.

---

## 6. Next Integration Priorities & Reference Map

1. **Wire Remaining Frontend Pages (`/overview`, `/comparative-analysis`, `/reports`) & Point/AOI Series:** Connect remaining placeholder routes to real Core `/api/v1/assessments*` or new backend comparison/report modules once designed, keeping synthetic/unavailable disclosures until connected.
2. **Complete GHS `temporal.py` Wiring, Raster-to-Series Transport & Live Postgres Testing:** Wire `integrate_rate_to_depth` / `aggregate_temporal_stack` inside `HarmonizationService.execute_plan`, close the GHS → Core artifact/time-series transport gap (`extensions.time_series` vs Zarr/GeoTIFF reading), evaluate AppEEARS/Harmony task support, and run `optional-live-and-postgres.yml` against provisioned PostgreSQL.
3. **Production Deployment Target & P2 Calibration:** Provision target container/hosting configuration outside placeholder state before adding CD push/deploy steps; conduct empirical benchmark calibration before enabling any P2 methods (`composite_tri`, `critical_slowing_down`, `causal_attribution`).

**Authoritative Documents:** [AGENTS.md](../AGENTS.md) · [SYSTEM_ARCHITECTURE.md](./architecture/SYSTEM_ARCHITECTURE.md) · [SCIENTIFIC_CORE.md](./scientific/SCIENTIFIC_CORE.md) · [ADR-0001](./adr/0001-bootstrap-stack.md) · [ADR-0002](./adr/0002-geospatial-harmonization-service.md) · [frontend/DESIGN.md](../frontend/DESIGN.md)
