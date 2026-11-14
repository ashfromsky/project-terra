# TERRA Geospatial Harmonization Service

Independent Python service (`geospatial-harmonization` / `geospatial_harmonization`, container image `terra-geospatial-harmonization`) implementing source-agnostic geospatial retrieval, format decoding, semantics-aware grid transformation, quality verification, and durable async execution for TERRA.

## Architecture

Layered modular structure (`api -> application -> domain <- infrastructure`):

- `domain/`: Pure grid (`GridSpec`, `SpatialBounds`, `AffineMatrix`), temporal (`TemporalSpec`), dataset (`SpatialDataset`, `DecodedDataset`), resampling policy (`ResamplingPolicy`), and `Protocol` ports (`DataHandler`, `AssetReader`, `GridTransformer`, `StoragePort`, `JobRepository`, `DatasetRepository`).
- `readers/`: Format-agnostic decoders (`GeoTIFFReader`, `NetCDFReader`, `HDF5Reader`, `HDF4Reader`, `ZarrReader`, `JSONReader`, `CSVReader`) and magic-byte/extension `ReaderRegistry`.
- `transformations/`: Provider-agnostic `TargetGridTransformer` (Rasterio/GDAL warp, center-to-corner affine adjustment), temporal rate-to-depth integration (`integrate_rate_to_depth`), and `QualityValidator`.
- `handlers/`: Retrieval and canonicalization (`MODISHandler`, `GPMIMERGHandler`, `SMAPHandler`, `NASAPowerHandler`, SSRF-guarded `GenericHandler`) registered in `HandlerRegistry`.
- `application/`: `HarmonizationService` end-to-end orchestration use case.
- `infrastructure/`: `LocalObjectStore`, `S3ObjectStore` (streaming & R2/S3 multipart uploads), SQLAlchemy async models (`ghs_datasets`, `ghs_assets`, `ghs_harmonization_jobs`, and storage ledger tables `ghs_storage_ledger`, `ghs_storage_reservations`, `ghs_storage_objects`, `ghs_storage_asset_refs`, `ghs_storage_audit_events`), PostgreSQL `FOR UPDATE SKIP LOCKED` & row-locked quota ledger repository, and Alembic migrations (`ghs_alembic_version`, through `0002_storage_ledger`).
- `storage/`: Quota guard (`StorageQuotaManager`), three-zone immutability & retention (`StorageZoneManager` for `raw/`, `intermediate/`, `derived/`), lossless precision-preserving compression (`DataCompressionManager`), SHA-256 deduplication (`ContentDeduplicationService`), mark-and-sweep cleanup (`StorageLifecycleManager`), and credential-safe telemetry (`StorageMonitoringService`).
- `api/` & `worker/`: FastAPI ASGI app (`geospatial_harmonization.main:app`) served by Granian and standalone bounded-concurrency polling `WorkerRunner` (`python -m geospatial_harmonization.worker`) with periodic reservation reconciliation and lifecycle maintenance.

## Endpoints

- Operational probes: `GET /health`, `GET /ready`, `GET {API_V1_PREFIX}/health`, `GET {API_V1_PREFIX}/ready` (default prefix `/api/v1`)
- Business API (`/api/v1`):
  - `GET /api/v1/capabilities` — registered provider handlers and readers
  - `POST /api/v1/jobs` — enqueue durable async harmonization job (`202 Accepted`)
  - `GET /api/v1/jobs/{job_id}` — inspect job state and linked `dataset_id`
  - `POST /api/v1/harmonize` — synchronous harmonization run returning `ProcessingResult` (`507` on quota exceeded, `413` on object/job/temp cap exceeded, `409` on immutability violation)
  - `GET /api/v1/datasets` and `GET /api/v1/datasets/{dataset_id}` — browse canonical dataset metadata
- Storage Governance & Telemetry API (`/api/v1/storage`):
  - `GET /api/v1/storage/usage` — ledger utilization, zone breakdown, warnings, and compression/dedup savings
  - `GET /api/v1/storage/policy` — active quota, zone retention, compression, and concurrency policies (redacts credentials/tokens)
  - `GET /api/v1/storage/health` — storage health, warning/critical state, orphan/missing object counts
  - `POST /api/v1/storage/reconcile` — admin-protected (`X-Admin-Token` or `Authorization: Bearer`) ledger vs. object-store reconciliation
  - `POST /api/v1/storage/cleanup` — admin-protected dry-run or live mark-and-sweep cleanup

## Configuration & Migrations

All runtime settings are defined via `pydantic-settings` in [`Settings`](src/geospatial_harmonization/config/settings.py) (`.env*` files are never committed per ADR 0001; see [GHS ADR 0003](docs/adr/0003-storage-quota-optimization-and-lifecycle.md) for storage design):

- Database: `DATABASE_URL` (`sqlite+aiosqlite:///./ghs.db` default; use `postgresql+asyncpg://...` in production)
- Storage backend: `STORAGE_BACKEND` (`local` or `s3`), `LOCAL_STORAGE_DIR`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`
- Quota & limits: `GHS_STORAGE_BUDGET_BYTES` (default `8000000000` / 8 GB application budget below 10 GB R2 allowance), `GHS_STORAGE_WARNING_THRESHOLD` (`0.80`), `GHS_STORAGE_HARD_LIMIT_THRESHOLD` (`1.00`), `GHS_STORAGE_MAX_OBJECT_BYTES` (`2147483648`), `GHS_STORAGE_MAX_JOB_OUTPUT_BYTES` (`1073741824`), `GHS_STORAGE_ESTIMATION_ENABLED` (`true`), `GHS_STORAGE_RESERVATION_TTL_SECONDS` (`3600`)
- Retention, compression & concurrency: `GHS_STORAGE_INTERMEDIATE_RETENTION_SECONDS`, `GHS_STORAGE_ORPHAN_GRACE_SECONDS`, `GHS_STORAGE_ABANDONED_TEMP_MAX_AGE_SECONDS`, `GHS_STORAGE_RAW_RETENTION_DAYS`, `GHS_STORAGE_DERIVED_RETENTION_DAYS`, `GHS_STORAGE_COMPRESSION_ENABLED`, `GHS_STORAGE_RASTER_CODEC` (`ZSTD` / `DEFLATE`), `GHS_STORAGE_RASTER_COG_ENABLED`, `GHS_STORAGE_ZARR_CODEC`, `GHS_STORAGE_ALLOW_LOSSY_COMPRESSION` (`false`), `GHS_STORAGE_DEDUP_ENABLED`, `GHS_STORAGE_MAX_WORKER_CONCURRENCY` (`2`), `GHS_STORAGE_TEMP_DIR`, `GHS_STORAGE_TEMP_MAX_BYTES`
- External access & admin security: `EARTHDATA_TOKEN`, `GENERIC_HANDLER_ALLOWED_HOSTS` (default empty = `GenericHandler` disabled), `GHS_ADMIN_TOKEN` (required for `/api/v1/storage/reconcile` and `/cleanup`; returns `503` if unset)

Run PostgreSQL schema migrations before starting production instances:

```bash
cd backend/services/geospatial_harmonization
uv run alembic upgrade head
```

## Running Locally & Docker

```bash
cd backend/services/geospatial_harmonization
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy src

# API server
uv run granian --interface asgi --host 127.0.0.1 --port 8080 geospatial_harmonization.main:app

# Background worker
uv run python -m geospatial_harmonization.worker

# Container build & run (API / Worker)
docker build -t terra-geospatial-harmonization .
docker run --rm -p 8080:8080 terra-geospatial-harmonization
docker run --rm terra-geospatial-harmonization python -m geospatial_harmonization.worker
```

To execute the live PostgreSQL `FOR UPDATE SKIP LOCKED` integration test (`tests/integration/test_postgres_locking.py`), export `GHS_TEST_POSTGRES_URL="postgresql+asyncpg://..."` and re-run `uv run pytest`.

## Verified Dependency Notes

- Verified on `x86_64-manylinux_2_28` with Python `3.13.16`: `rasterio` (`1.5.2`), `pyhdf` (`0.11.7`), `h5py`, `netCDF4`, `pyproj`, `shapely`, `xarray`, `rioxarray`, and `zarr` install from prebuilt binary wheels without compilation on Debian Bookworm (`python:3.13-slim-bookworm`).
