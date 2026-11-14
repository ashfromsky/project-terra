# ADR 0002 — Geospatial Harmonization Service Boundary

- **Status:** Accepted
- **Date:** 2026-11-14
- **Scope:** Root service topology (`docs/architecture/SYSTEM_ARCHITECTURE.md`, `backend/services/geospatial_harmonization/`).

## Context

`SYSTEM_ARCHITECTURE.md` establishes a modular-monolith baseline in `backend/core/` and requires an ADR before introducing an independently deployed service. The Geospatial Harmonization Service (GHS) requires a heavy native geospatial stack (`GDAL`/`rasterio`, `pyhdf`/HDF4, `h5py`, `netCDF4`, `pyproj`, `shapely`, `xarray`, `rioxarray`, `zarr`) and runs memory-intensive raster decoding, reprojection, and external satellite ingestion workflows.

## Decisions

1. **Independently deployable service.** Implement GHS under `backend/services/geospatial_harmonization/` (service `geospatial-harmonization`, package `geospatial_harmonization`, Docker image `terra-geospatial-harmonization`) rather than embedding GDAL/HDF4/HDF5 native dependencies into `backend/core/`.
2. **Preserved TERRA layering and contracts.** Internally, GHS follows TERRA's layered boundaries (`api -> application -> domain <- infrastructure`), uses Repository `Protocol` contracts, and leaves `backend/core/`, `backend/scientific/`, `backend/worker/`, and `frontend/` untouched.
3. **API versioning and probes.** Business routes mount under configurable `API_V1_PREFIX` (`/api/v1` by default, aligning with Caddy `/api/*` routing and `AGENTS.md` §5.2). Operational probes mount at `/health`, `/ready`, and `{API_V1_PREFIX}/health`, `{API_V1_PREFIX}/ready`.
4. **Database ownership and durable job queue.** GHS owns its own SQLAlchemy models, Alembic migrations, job table, and dataset metadata records (even when sharing a PostgreSQL server). Asynchronous jobs use PostgreSQL `FOR UPDATE SKIP LOCKED` per `SYSTEM_ARCHITECTURE.md` §4.9 without introducing Redis or RabbitMQ.

## Consequences

- `backend/core/` remains lightweight while GHS can scale and build its native geospatial container independently.
- PostgreSQL integration tests are required to validate `SKIP LOCKED` concurrency, while SQLite (`aiosqlite`) supports fast local unit and repository tests.
- Revisit merging or RPC boundaries only if TERRA requires tight transactional coupling across core analyses and harmonization runs.
