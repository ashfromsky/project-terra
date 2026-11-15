# PROJECT TERRA

**Ecosystem Response & Resilience Intelligence**

TERRA is an open-source environmental analysis platform designed to investigate how ecosystems respond to environmental stress, change over time, and recover from disturbances.

The project aims to transform Earth observation data into interpretable environmental insights through remote sensing, time-series analysis, and ecosystem resilience assessment.

> Project status: Active development. Core API (`auth`, `layers`, `regions`, `data_sources`, `assessments`), P0/P1 Scientific Core (`terra-scientific`), Core Worker (`terra-worker`), isolated Geospatial Harmonization Service (`GHS`, ADR-0002) with bounded multi-granule ingestion and temporal harmonization, all six analytical/workspace React/Vite routes (`/overview`, `/explore`, `/data-sources`, `/assessments`, `/comparative-analysis`, `/reports`), and offline GitHub Actions CI are implemented. P2 scientific methods (`composite_tri`, `critical_slowing_down`, `causal_attribution`), AppEEARS/Harmony task polling, and external production deployment remain in progress or deferred.

## Overview

Environmental changes such as droughts, heatwaves, and long-term precipitation shifts can significantly affect ecosystems.

TERRA aims to help investigate these processes by combining multiple environmental indicators and analyzing their temporal relationships.

Instead of relying exclusively on vegetation indices or individual satellite observations, TERRA focuses on ecosystem response dynamics.

## Main Objectives

- Detect long-term environmental trends.
- Investigate ecosystem responses to environmental stress.
- Evaluate vegetation resistance and recovery.
- Compare environmental dynamics across geographic regions.
- Identify potential signs of ecosystem vulnerability.
- Present analytical results with transparent data provenance and uncertainty.

## Scientific Approach

TERRA is being designed around several analytical dimensions:

| Dimension | Description |
|---|---|
| Resistance | How well an ecosystem maintains its characteristics during environmental stress. |
| Recovery | How quickly and completely observed indicators return toward their baseline after disturbance. |
| Stability | How much ecosystem indicators fluctuate over time. |
| Sensitivity | How strongly ecosystem indicators respond to environmental changes. |

These dimensions are intended to form the foundation of a future integrated resilience assessment model.

All metrics and aggregation methods require appropriate scientific justification and validation.

## Data Sources

Planned environmental data sources include:

- **NASA MODIS** — vegetation indices (NDVI, EVI) and land surface temperature.
- **NASA GPM IMERG** — precipitation estimates.
- **NASA SMAP** — soil moisture observations.
- **NASA POWER** — meteorological and solar data.

The availability, temporal coverage, spatial resolution, and quality of each dataset will be considered during analysis.

## Technology Stack

### Frontend

- React 19
- TypeScript
- Vite
- MapLibre GL JS
- deck.gl
- Zustand
- TanStack Query
- Apache ECharts

### Backend

- Python
- FastAPI
- Granian
- Pydantic

### Data and Scientific Computing

Implemented in `backend/scientific/` (`terra-scientific`) and `backend/services/geospatial_harmonization/`:

- NumPy, SciPy, Pandas, Pydantic (pure Scientific Core `terra-scientific`, zero HTTP/DB dependencies)
- Xarray, Rasterio, GeoPandas, h5py, netCDF4, Zarr, Shapely (inside isolated `geospatial_harmonization` service per ADR-0002)
- SQLAlchemy async (`aiosqlite` development fallback; `asyncpg`/PostgreSQL supported in config)

Planned / Target infrastructure (not currently wired in runtime):

- PostGIS spatial queries in Core
- DuckDB analytical engine
- TiTiler dynamic COG/Zarr tile service
- Caddy reverse proxy and PgBouncer connection pooling

### Development & CI

- pnpm, uv, Vitest, pytest, Ruff, mypy (strict on Scientific Core, Worker, GHS), ESLint, TypeScript
- GitHub Actions workflows in `.github/workflows/`:
  - `ci.yml`: Offline lint, strict mypy, unit/integration tests (`backend-core`, `scientific-core`, `worker`, `ghs-offline`, `frontend-and-contracts`), `make dev-check`, OpenAPI contract synchronization verification (`make contracts`), Vite production build (`frontend/dist` artifact), and GHS container image build verification (`cd-artifact-readiness`).
  - `optional-live-and-postgres.yml`: Manual `workflow_dispatch` workflow for GHS PostgreSQL `FOR UPDATE SKIP LOCKED` integration tests and optional `EARTHDATA_TOKEN`-gated live NASA smoke tests.

#### Deployment Readiness

No external hosting provider, container registry target, or deployment credentials are configured in the repository yet. To enable automated deployment beyond the CI artifact stage (`terra-frontend-dist` and local `terra-ghs:ci` Docker build check):

1. Add a container registry destination (e.g., GHCR) and Dockerfiles for `backend/core`, `backend/worker`, and `frontend` static serving alongside `backend/services/geospatial_harmonization/Dockerfile`.
2. Provision production PostgreSQL/PostGIS, S3-compatible object storage, and configured secrets (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `JWT_SECRET_KEY`, `DATABASE_URL`, `GHS_DATABASE_URL`, `EARTHDATA_TOKEN`).
3. Add a deployment job scoped to protected environment approvals in GitHub Actions referencing those configured secrets.

Run locally from the repository root via `Makefile` (requires Node.js 20+ with `pnpm`, `uv`, and Python 3.13+):

- **Frontend only:** `cd frontend && pnpm dev` (or `make frontend-dev`) — regenerates OpenAPI/TypeScript contracts via `predev` and starts Vite (`http://localhost:5173`) with `/api` and `/health` proxied to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`).
- **Main development environment:** `make dev` — regenerates contracts, then starts `backend/core` (`http://127.0.0.1:8000`, `/health`, `/health/ready`), `CORE-WORKER` (`terra-worker`), and Vite (`http://localhost:5173`).
- **GHS-only environment:** `make dev-ghs` — starts the isolated Geospatial Harmonization Service API (`http://127.0.0.1:8080`, `/health`, `/ready`) and `GHS-WORKER` as separate processes sharing `GHS_DATABASE_URL` and local/S3 storage. Run components individually with `make ghs-api-dev`, `make ghs-worker-dev`, and `make ghs-migrate`.
- **Complete local environment:** `make dev-full` — regenerates contracts and starts all five independent processes (`CORE`, `GHS`, `CORE-WORKER`, `GHS-WORKER`, `FRONTEND`) with health checks, shared Core `DATABASE_URL` / independent `GHS_DATABASE_URL`, and unified addressing (`8000` / `8080` / `5173`). Core consumes GHS over HTTP (`GHS_BASE_URL`) per ADR-0002.
- **Environment diagnostics & utilities:** `make doctor` (validates CLIs, config, DB isolation, ports `8000`/`8080`/`5173`, workers, storage, and credential readiness without printing secrets), `make backend-dev`, `make worker-dev`, `make contracts`, `make test` (Core + Scientific + Worker + Frontend), `make ghs-test`, `make dev-check` (orchestrator tests), `make lint`, `make ghs-lint`, `make frontend-typecheck`, `make frontend-build`. See [`docs/ENVIRONMENT_SETUP.md`](docs/ENVIRONMENT_SETUP.md).

#### Environment & Process Supervision

- **Configuration:** All services read the root `.env` (copied from `.env.example`, never committed) with default SQLite persistence isolated in `<repo>/.data/terra.db` (shared by `CORE` + `CORE-WORKER` via `DATABASE_URL`) and `<repo>/.data/ghs.db` (shared by `GHS` + `GHS-WORKER` via `GHS_DATABASE_URL`). Optional port overrides: `CORE_HOST`, `CORE_PORT` (default `8000`), `GHS_HOST`, `GHS_PORT` (default `8080`), `FRONTEND_PORT` (default `5173`).
- **Logs & shutdown:** `scripts/dev.mjs` prefixes logs (`[CONTRACTS]`, `[CORE]`, `[CORE-WORKER]`, `[GHS]`, `[GHS-WORKER]`, `[FRONTEND]`), validates port availability, waits for `/health` before launching dependent workers, and shuts down all child process groups cleanly on `Ctrl+C` (`SIGINT`/`SIGTERM`).

## Architecture

TERRA is intended to follow a modular architecture with independently runnable frontend and backend components.

The planned system includes:

- Frontend — interactive maps, visualizations, and analytical interfaces.
- Backend — API, application orchestration, and job management.
- Scientific Core — independent scientific calculations and statistical methods.
- Analytical Engine — analytical processing of environmental datasets.
- Worker — asynchronous execution of computationally intensive tasks.
- Data Storage — structured metadata and geospatial data storage.

The initial implementation will prioritize a modular monolith rather than unnecessary distributed infrastructure.

## Scientific Principles

TERRA aims to follow several principles:

1. Reproducibility — analytical results should be reproducible from documented inputs and methods.
2. Data provenance — sources, product versions, processing steps, and retrieval dates should be traceable.
3. Quality awareness — missing observations and satellite quality flags must be considered.
4. Spatial and temporal consistency — datasets with different resolutions and sampling intervals must be appropriately harmonized.
5. Scientific transparency — assumptions, limitations, and uncertainty must be communicated.
6. No unsupported causal claims — statistical relationships alone do not establish causality.

## Project Status

TERRA is in active development with Core API (`auth`, `layers`, `regions`, `data_sources`, `assessments`), `terra-scientific` v1.1.0, `terra-worker`, GHS (isolated geospatial ingestion service with bounded multi-granule workflows & temporal harmonization), and all six workspace routes connected (`/overview`, `/explore`, `/data-sources`, `/assessments`, `/comparative-analysis`, `/reports`). Several P2 scientific methods, AppEEARS/Harmony polling, and production deployment remain deferred:

- [x] Repository and development environment initialization (`make dev-full`, `make doctor`, unified ports `8000`/`8080`/`5173`).
- [x] Frontend and backend Core API integration (`auth` including dev-only `dev-session`, `layers`, `regions`, `data_sources`, `assessments` + `compare`).
- [x] Offline Scientific Core time-series pipeline (`terra-scientific`: climatology, disturbance detection, OLS cross-variable regression, consecutive-step recovery, and Resistance/Recovery/Stability/Sensitivity resilience dimensions).
- [x] GHS multi-granule ingestion, `temporal.py` harmonization (`integrate_rate_to_depth` / `aggregate_temporal_stack`) wired into `HarmonizationService.execute_plan`, and `extensions["time_series"]` consumption by Core/`terra-scientific`.
- [x] Live Core API integration across `/overview`, `/explore`, `/data-sources`, `/assessments`, `/comparative-analysis`, and `/reports` (including Apache ECharts diagnostics & JSON/CSV/Markdown/PDF exports).
- [ ] AppEEARS/Harmony task submission workflows and streaming COG/Zarr tile serving (TiTiler).
- [ ] P2 scientific methods (spatial trend mapping, regime shifts, causal attribution) and calibrated composite TRI benchmarks (`composite_tri` remains withheld/`unavailable_unvalidated`).
- [ ] Production deployment environment, container registry, and hosting secrets configuration.

## Open Source

TERRA is intended to be an open-source project.

License: Apache License 2.0.

See [LICENSE](LICENSE) for details.

## Disclaimer

TERRA is an experimental environmental analysis project.

Its outputs should not be interpreted as definitive ecological assessments, forecasts, or proof of causal relationships without appropriate scientific validation.

## Acknowledgements

Developed as part of the NASA Space Apps Challenge 2026.

TERRA is an independent project and is not an official NASA product or service.