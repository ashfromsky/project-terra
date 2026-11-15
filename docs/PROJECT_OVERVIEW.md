# PROJECT TERRA — Global Project Overview & Current State

> **Living Document Mandate:** This file is the repository-level source of truth for the global state of `PROJECT TERRA`. Per [AGENTS.md](../AGENTS.md), agents MUST read this document before non-trivial tasks and update it whenever global changes alter active services, module boundaries, data/API integration, mock status, or verification tooling.

**Baseline Snapshot:** `feat/complete_terra_integration` (`2026-11-15`)

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

Currently, `frontend/` connects to `backend/core/` through generated OpenAPI TypeScript contracts (single source of truth), `backend/core/` integrates `backend/scientific/` (`terra-scientific`) for deterministic Scientific Assessments + paired assessment comparison (`POST /api/v1/assessments/compare`) and communicates over HTTP with `backend/services/geospatial_harmonization/` (GHS, default `http://127.0.0.1:8080`) for provider readiness, granule discovery, async ingestion jobs, and prepared temporal datasets (`data_sources` module), while `backend/worker/` executes queued Core assessments asynchronously (`claim_next_queued()`):

```text
project-terra/
├── frontend/                                 # React 19 / Vite 8 / MapLibre 5 / deck.gl 9 / d3-geo / ECharts 6 SPA (pnpm)
│   └── src/shared/api/generated/             # auto-generated openapi.json + schema.d.ts (openapi-fetch)
├── backend/
│   ├── core/                                 # terra-core FastAPI API (System, Auth + dev-session, Regions CRUD, 16 Layers, Data Sources, Assessments + Compare)
│   ├── scientific/                           # terra-scientific P0+P1 pure Python Scientific Core package (P2 deferred)
│   ├── worker/                               # terra-worker async Scientific Assessment queue runner (polls Core DB + fetches GHS)
│   └── services/geospatial_harmonization/    # ADR-0002 isolated service (API + WorkerRunner + Multi-Granule Batch + temporal.py + S3/Local + Alembic)
└── docs/
    ├── PROJECT_OVERVIEW.md                   # This living global state summary
    ├── ENVIRONMENT_SETUP.md                  # Unified 5-process setup, DB isolation, make doctor, and NASA credentials
    ├── architecture/SYSTEM_ARCHITECTURE.md   # Target architecture baseline
    ├── scientific/SCIENTIFIC_CORE.md         # Scientific Core methods, data contracts, QA rules, & P0/P1/P2 status
    └── adr/                                  # ADR-0001 (stack) & ADR-0002 (GHS service boundary)
```

---

## 3. Component Readiness Matrix

| Component | Location | Status | Implemented Capabilities & Actual Gaps |
| :--- | :--- | :--- | :--- |
| **Frontend SPA** | `frontend/` | **Connected End-to-End Across All 6 Workspaces** | FSD-lite (`app -> pages -> widgets -> features -> entities -> shared`). 7 routes (`/`, `/overview`, `/explore`, `/comparative-analysis`, `/assessments`, `/reports`, `/data-sources`). Vite dev proxy routes `/api` and `/health` to `backend/core`. `TopNavigation` integrates `/api/v1/auth/*` (including dev-only `POST /api/v1/auth/dev-session` when `devAuthEnabled=true`) and `/api/v1/system/info`. `/explore` integrates `/api/v1/layers*`, Equal Earth / Globe / Mercator + NASA GIBS browse imagery, and `/api/v1/regions*` AOI CRUD with deep-link handoffs into `/data-sources?regionId=...` and `/assessments?regionId=...` (synthetic visual overlays stay explicitly isolated behind `syntheticPreviewEnabled`). `/data-sources` integrates provider readiness, granule discovery, bounded GHS ingestion triggering + polling, one-click multi-domain adaptive bundle provisioning (`POST /api/v1/data-sources/provision`), prepared dataset inspection with QA-layer/span metadata & Apache ECharts time-series previews, `/layers` catalog, and `/assessments` provenance. `/assessments` auto-evaluates `POST /api/v1/assessments/readiness` pre-run (showing required vs. observed criteria, `Passed`/`Warning`/`Failed` badges, missing gaps, remediations, metric availability, and one-click auto-provisioning), executes assessments via `terra-worker`, renders detailed post-run readiness/limitation diagnostics without bare `Insufficient Data`, plus Apache ECharts time-series & Z-score anomaly charts, 4 separated resilience dimensions, negative-peak event resistance traceability, cross-variable tables, quality reports, uncertainty, and provenance. `/comparative-analysis` calls `POST /api/v1/assessments/compare` for dual-run ECharts overlays and statistical/resilience deltas. `/reports` renders provenance summaries and exports `.json`, `.csv`, `.md`, plus print/PDF layouts. `/overview` displays live Core/GHS service metrics, workspace counts, and guided workflow cards. |
| **Core Backend API** | `backend/core/` | **Implemented (P0 + GHS Data Sources Proxy + Adaptive Provisioning/Readiness + Scientific & Comparison + Object Storage)** | `terra-core` (`0.1.0`, Python `>=3.13`, FastAPI, Granian, SQLAlchemy asyncio, Pydantic Settings reading root `../../.env` and `.env`, PyJWT, HTTPX, `boto3` S3/R2 SigV4 client, `asyncpg`/`aiosqlite` with shared dev SQLite `.data/terra.db` fallback). Preserves ADR-0002 separation (zero GDAL/rasterio/GHS imports) by calling GHS via `HttpxGhsServiceClient` / `HttpxGhsDatasetClient` (`http://127.0.0.1:8080` default) and running `terra-scientific` off the event loop (`asyncio.to_thread`). Uses `ObjectStoragePort` (`LocalCoreObjectStore` / `S3CoreObjectStore` under `core/` prefix with short-lived presigned GET URLs) for assessment `result.json` + `provenance.json` artifacts and supports remote GHS raster download fallback (`asset-content`). Routes: `/health`, `/health/live`, `/health/ready` (checks database + object storage), `/api/v1/health`, `/api/v1/system/info` (exposes `storageBackend`), `/api/v1/auth/github/{login,callback}`, `/api/v1/auth/{logout,me}`, `/api/v1/auth/dev-session` (development-only), `/api/v1/regions*`, `/api/v1/layers*` (16-layer catalog), `/api/v1/data-sources/{providers,discover,provision,ingestions,ingestions/{id},datasets,datasets/{id},datasets/{id}/download-url,datasets/{id}/download}`, `/api/v1/assessments/methods`, `/api/v1/assessments/readiness`, `/api/v1/assessments*`, `/api/v1/assessments/{id}/artifacts*`, and `/api/v1/assessments/compare`. **Gaps:** Schema auto-created in non-production (`Base.metadata.create_all`; no Alembic in Core yet); no standalone `ai_analyst` module. |
| **Scientific Core** | `backend/scientific/` | **Implemented (P0 & P1 + Adaptive Readiness Engine; P2 deferred)** | `terra-scientific` (`0.1.0`, `numpy`, `pandas`, `pydantic`, `scipy`; optional `[geospatial]` extra for GeoTIFF). Implements source- and method-aware Adaptive Data Readiness specifications (`READINESS_SPEC_VERSION = "1.0.0"`, `evaluate_assessment_readiness`), source-aware QA & scale/fill policies (`MOD13Q1.061`, `MOD11A2.061`, `GPM_3IMERGHH.07/.06` half-hourly rate-to-depth `mm/hr * 0.5`, `SPL3SMP_E.006` AM/PM split, `NASA_POWER` `MERRA-2`/`CERES SYN1deg`), `NASA GIBS` quantitative rejection, multi-variable `map_ghs_dataset_payload` mapping GHS `extensions["time_series"]`, intensive/extensive temporal aggregation, stratified climatologies with overlap-leakage prevention, parametric/robust/percentile anomalies, exact ($n \le 10$) + tie-corrected Mann–Kendall, Hirsch–Slack Seasonal MK, elapsed-time Sen's slope + Gilbert CI, lag-k ACF / Ljung–Box Q / ESS / opt-in Hamed–Rao & Yue–Wang TFPW, area-weighted zonal statistics, chunked pixel MK+Sen + Benjamini–Hochberg FDR, Moran's I & Getis–Ord $G_i^*$, deseasonalized cross-variable Pearson/Spearman/lag/OLS+VIF/partial correlation, Pettitt (1979) structural break detection, consecutive-confirmation post-event recovery, separated Resistance/Recovery/Stability/Sensitivity metrics, graceful partial pipeline execution (`completed` / `completed_partial` / `insufficient_data` with persisted `readiness` diagnostics), 3-tier uncertainty, and SHA-256 provenance/JSON artifact writer (`1.1.0`). **Deferred (P2):** `composite_tri` (`unavailable_unvalidated`), `critical_slowing_down`, and `causal_attribution` remain `implemented=False`. |
| **Shared Core Worker** | `backend/worker/` | **Implemented (`terra-worker`)** | Async queue runner (`AssessmentWorkerRunner`, CLI `python -m terra_worker`) sharing `DATABASE_URL` and `ObjectStoragePort` (`LocalCoreObjectStore`/`S3CoreObjectStore`) with `terra-core`, claiming `queued` rows via `claim_next_queued()` (`FOR UPDATE SKIP LOCKED` on PostgreSQL, atomic conditional update on SQLite), resolving GHS datasets + remote raster assets via `HttpxGhsDatasetClient`, executing `ScientificAssessmentService`, persisting deterministic JSON payloads & `result.json`/`provenance.json` artifacts to object storage, and isolating job failures (`status="failed"`). Supervised alongside all services in `make dev` and `make dev-full`. **Gaps:** Live PostgreSQL `SKIP LOCKED` execution verified in staging when configured. |
| **Geospatial Harmonization Service (GHS)** | `backend/services/geospatial_harmonization/` | **Implemented (ADR-0002 service)** | Separate FastAPI + Granian app (`http://127.0.0.1:8080` default), `Dockerfile`, Alembic (`0003_job_retry_and_idempotency`), dedicated `GHS_DATABASE_URL` (default `<repo>/.data/ghs.db` in `dev-full`, isolated from Core `DATABASE_URL`), `WorkerRunner` (`FOR UPDATE SKIP LOCKED` on PostgreSQL, SQLite fallback), `LocalObjectStore` & `S3ObjectStore` (SigV4 path-style R2/S3 with `normalize_s3_endpoint_url`, bounded 256 MB LRU tile cache, zone-scoped orphan sweeps for `raw/`/`intermediate/`/`derived/`, and presigned GET URLs), chronological paginated CMR discovery + uniform multi-year granule stratification (`select_representative_granules`, `max_granules <= 256`) & AOI spatial reduction in `MODISHandler`, `GPMIMERGHandler`, `SMAPHandler`, and `NASAPowerHandler`, SSRF-guarded `GenericHandler` (disabled), `TargetGridTransformer`, `QualityValidator`, `temporal.py` (`integrate_rate_to_depth` & `aggregate_temporal_stack`) with QA-layer/valid-count/semantics preservation wired inside `HarmonizationService.execute_plan`, producing standardized `extensions["time_series"]` series per variable for Core/Scientific Core, plus `/api/v1/{providers,discover,jobs,harmonize,datasets,datasets/{id}/asset-content,datasets/{id}/asset-url,datasets/derived,storage}` endpoints. **Gaps:** AppEEARS & Harmony async remote task polling remains unimplemented (direct CMR/DAAC & NASA POWER ingestion is operational). |
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
  - `make dev-full` / `make doctor` / `make dev-check`: validates runtime dependencies, DB isolation, and ports `8000`/`8080`/`5173`, and launches all 5 processes (`CORE`, `GHS`, `CORE-WORKER`, `GHS-WORKER`, `FRONTEND`) cleanly. See [ENVIRONMENT_SETUP.md](./ENVIRONMENT_SETUP.md).

---

## 6. Next Integration Priorities & Reference Map

1. **AppEEARS / Harmony Tasks & Dynamic Raster Tile Streaming:** Add async AppEEARS/Harmony polling workflows in GHS and dynamic COG/Zarr tile serving (TiTiler) alongside PostGIS/DuckDB storage scaling when warranted.
2. **PostgreSQL & Live NASA Earthdata Validation in Deployed Staging:** Execute `optional-live-and-postgres.yml` against provisioned PostgreSQL (`GHS_TEST_POSTGRES_URL`) and live `EARTHDATA_TOKEN` runs in staging.
3. **Production Deployment Target & P2 Calibration:** Provision target container/hosting configuration outside placeholder state before adding CD push/deploy steps; conduct empirical benchmark calibration before enabling any P2 methods (`composite_tri`, `critical_slowing_down`, `causal_attribution`).

**Authoritative Documents:** [AGENTS.md](../AGENTS.md) · [ENVIRONMENT_SETUP.md](./ENVIRONMENT_SETUP.md) · [SYSTEM_ARCHITECTURE.md](./architecture/SYSTEM_ARCHITECTURE.md) · [SCIENTIFIC_CORE.md](./scientific/SCIENTIFIC_CORE.md) · [ADR-0001](./adr/0001-bootstrap-stack.md) · [ADR-0002](./adr/0002-geospatial-harmonization-service.md) · [frontend/DESIGN.md](../frontend/DESIGN.md)
