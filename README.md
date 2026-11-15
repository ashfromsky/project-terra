# PROJECT TERRA

**Ecosystem Response & Resilience Intelligence**

TERRA is an open-source environmental analysis platform designed to investigate how ecosystems respond to environmental stress, change over time, and recover from disturbances.

The project aims to transform Earth observation data into interpretable environmental insights through remote sensing, time-series analysis, and ecosystem resilience assessment.

> Project status: Active development. Core API (`auth`, `layers`, `regions`, `assessments`), P0/P1 Scientific Core (`terra-scientific`), Core Worker (`terra-worker`), isolated Geospatial Harmonization Service (`GHS`, ADR-0002), React/Vite frontend flows (`/explore`, `/assessments`, `/data-sources`), and offline GitHub Actions CI are implemented. Remaining UI pages (`/overview`, `/comparative-analysis`, `/reports`), full GHS temporal/transport wiring into Core, P2 scientific methods (`composite_tri`, `critical_slowing_down`, `causal_attribution`), and external production deployment remain in progress or deferred.

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
- **Main development environment:** `make dev` — regenerates contracts, then starts `backend/core` (`http://127.0.0.1:8000`, `/health`, `/health/ready`) and Vite (`http://localhost:5173`).
- **GHS-only environment:** `make dev-ghs` — starts the isolated Geospatial Harmonization Service API (`http://127.0.0.1:8080`, `/health`, `/ready`) and `WorkerRunner` as separate processes sharing the same GHS configuration, database, and storage. Run components individually with `make ghs-api-dev`, `make ghs-worker-dev`, and `make ghs-migrate`.
- **Complete local environment:** `make dev-full` — regenerates contracts and starts all four independent processes (`CORE`, `FRONTEND`, `GHS`, `GHS-WORKER`). Starting all four processes does not imply Core ↔ GHS integration; GHS remains isolated per ADR-0002.
- **Standalone & utility targets:** `make backend-dev`, `make worker-dev`, `make contracts`, `make test` (Core + Scientific + Worker + Frontend), `make ghs-test`, `make dev-check` (orchestrator tests), `make lint`, `make ghs-lint`, `make frontend-typecheck`, `make frontend-build`.

#### Environment & Process Supervision

- **Configuration:** Core and Vite read root `.env` (and `backend/core/.env` for Core); GHS API and Worker both run from `backend/services/geospatial_harmonization/` and share its `.env` (never committed). Optional port overrides: `CORE_HOST`, `CORE_PORT` (default `8000`), `GHS_HOST`, `GHS_PORT` (default `8080`), `FRONTEND_PORT` (default `5173`).
- **Logs & shutdown:** `scripts/dev.mjs` prefixes logs (`[CONTRACTS]`, `[CORE]`, `[FRONTEND]`, `[GHS]`, `[GHS-WORKER]`), checks port availability before launch, and shuts down all child process groups cleanly on `Ctrl+C` (`SIGINT`/`SIGTERM`) or if any child exits unexpectedly.

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

TERRA is in active development with Core API (`auth`, `layers`, `regions`, `assessments`), `terra-scientific` v1.1.0, `terra-worker`, GHS (isolated geospatial ingestion service), and frontend integration for `/assessments` and `/data-sources` implemented. Several scientific methods, GHS temporal/transport paths, and analytical frontend pages remain partial or deferred:

- [x] Repository and development environment initialization.
- [x] Frontend and backend Core API foundation (`auth`, `layers`, `regions`, `assessments`).
- [x] Offline Scientific Core time-series pipeline (`terra-scientific`: climatology, disturbance detection, OLS cross-variable regression, consecutive-step recovery, and Resistance/Stability/Sensitivity resilience dimensions).
- [x] GHS raster ingestion, harmonization, and `terra-worker` job execution.
- [ ] GHS temporal aggregation wiring into `HarmonizationService.execute_plan`, AppEEARS/Harmony providers, and unified Core→GHS time-series transport (`extensions.time_series`).
- [ ] P2 scientific methods (spatial trend mapping, regime shifts, counterfactual assessment) and calibrated composite TRI benchmarks.
- [ ] Live Core API integration for analytical pages still using synthetic/placeholder views (`/overview`, `/comparative-analysis`, `/reports`).
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