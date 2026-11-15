# TERRA Geospatial Harmonization Service

Independent Python service (`geospatial-harmonization` / `geospatial_harmonization`, container image `terra-geospatial-harmonization`) implementing source-agnostic geospatial retrieval, format decoding, semantics-aware grid transformation, quality verification, and durable async execution for TERRA.

## Architecture

Layered modular structure (`api -> application -> domain <- infrastructure`):

- `domain/`: Pure grid (`GridSpec`, `SpatialBounds`, `AffineMatrix`), temporal (`TemporalSpec`), dataset (`SpatialDataset`, `DecodedDataset`), resampling policy (`ResamplingPolicy`), and `Protocol` ports (`DataHandler`, `AssetReader`, `GridTransformer`, `StoragePort`, `JobRepository`, `DatasetRepository`).
- `readers/`: Format-agnostic decoders (`GeoTIFFReader`, `NetCDFReader`, `HDF5Reader`, `HDF4Reader`, `ZarrReader`, `JSONReader`, `CSVReader`) and magic-byte/extension `ReaderRegistry`.
- `transformations/`: Provider-agnostic `TargetGridTransformer` (Rasterio/GDAL warp, center-to-corner affine adjustment), temporal rate-to-depth integration (`integrate_rate_to_depth`), and `QualityValidator`.
- `handlers/`: Retrieval and canonicalization (`MODISHandler`, `GPMIMERGHandler`, `SMAPHandler`, `NASAPowerHandler`, SSRF-guarded `GenericHandler`) registered in `HandlerRegistry`.
- `application/`: `HarmonizationService` end-to-end orchestration use case.
- `infrastructure/`: `LocalObjectStore`, `S3ObjectStore` (streaming & R2/S3 multipart uploads), SQLAlchemy async models (`ghs_datasets`, `ghs_assets`, `ghs_harmonization_jobs`, and storage ledger tables `ghs_storage_ledger`, `ghs_storage_reservations`, `ghs_storage_objects`, `ghs_storage_asset_refs`, `ghs_storage_audit_events`), PostgreSQL `FOR UPDATE SKIP LOCKED` & row-locked quota ledger repository, and Alembic migrations (`ghs_alembic_version`, through `0003_job_retry_and_idempotency`).
- `storage/`: Quota guard (`StorageQuotaManager`), three-zone immutability & retention (`StorageZoneManager` for `raw/`, `intermediate/`, `derived/`), lossless precision-preserving compression (`DataCompressionManager`), SHA-256 deduplication (`ContentDeduplicationService`), mark-and-sweep cleanup (`StorageLifecycleManager`), and credential-safe telemetry (`StorageMonitoringService`).
- `api/` & `worker/`: FastAPI ASGI app (`geospatial_harmonization.main:app`) served by Granian and standalone bounded-concurrency polling `WorkerRunner` (`python -m geospatial_harmonization.worker`) with classified retry/fail-fast error handling (`ErrorCategory`), exponential backoff (`next_retry_at`), cooperative cancellation, periodic reservation reconciliation, and lifecycle maintenance.

## NASA Earth Observation Providers

GHS includes dedicated scientific handlers and a unified catalog (`handlers/catalog.py`):

| Provider | Products | Native Grid / CRS | Temporal Cadence | Auth / Notes |
| :--- | :--- | :--- | :--- | :--- |
| `modis` | `MOD13Q1.061` (250 m), `MOD11A2.061` (1000 m) | MODIS Sinusoidal (`SR-ORG:6974`), HDF4 | 16-day / 8-day composites | CMR search (no auth required) + EDL Bearer / URS session redirect; decodes `pixel_reliability`, `VI Quality`, `QC_Day`/`QC_Night` bitmasks and scale/fill semantics |
| `gpm_imerg` | `GPM_3IMERGHH.07` / `.06`, `Early` / `Late` | `0.1 deg` (~10 km) WGS84, HDF5 / NetCDF4 | 30-min intervals | CMR search + EDL Bearer / URS; keeps `mm/hour` rate distinct from integrated `mm` depth; checks `precipitationQualityIndex` & liquid probability |
| `smap` | `SPL3SMP_E.006` (`AM`/`PM`) | 9 km EASE-Grid 2.0 (`EPSG:6933`), ~36 km native radiometer footprint, HDF5 | Daily AM/PM overpass | CMR search + EDL Bearer / URS; enforces `retrieval_qual_flag` (`0`/`8` recommended) & `surface_flag` (frozen ground, snow/ice, water); unavailable != `0` |
| `nasa_power` | `power_daily`, `power_hourly`, `nasa_power` | `0.5x0.625 deg` MERRA-2 / `1.0x1.0 deg` CERES SYN1deg (`EPSG:4326` JSON) | Daily / Hourly | Public NASA POWER API (never sends `EARTHDATA_TOKEN`); regional mode requires `>= 2.0 deg` span and batches wide/long-span requests |

> **Token note:** Protected direct DAAC downloads (`data.lpdaac.earthdatacloud.nasa.gov`, `data.gesdisc.earthdata.nasa.gov`, `data.nsidc.earthdatacloud.nasa.gov`) require an Earthdata Login (EDL) User Token from `https://urs.earthdata.nasa.gov/user_tokens`. Public NASA CMR granule search and NASA POWER operate without an EDL token. Redirects never forward `Authorization` or cookies to unrelated hosts (`EARTHDATA_PRESIGNED_HOSTS` defaults to `*.cloudfront.net,*.amazonaws.com`).

## Endpoints

- Operational probes: `GET /health`, `GET /ready`, `GET {API_V1_PREFIX}/health`, `GET {API_V1_PREFIX}/ready` (default prefix `/api/v1`)
- Business & Ingestion API (`/api/v1`):
  - `GET /api/v1/capabilities` — registered providers, products, readers, and non-secret provider enablement/token configuration status
  - `GET /api/v1/providers` — detailed provider/product/variable catalog and configuration status (no secrets exposed)
  - `POST /api/v1/discover` — discover available observations for a `provider`, `product`, `bbox`, and time window via CMR or NASA POWER
  - `POST /api/v1/jobs` — enqueue durable async harmonization job (`202 Accepted`) with `idempotency_key` deduplication and provider-enabled guard
  - `GET /api/v1/jobs/{job_id}` — inspect job state, `progress_pct`, `error_category`, `next_retry_at`, and linked `dataset_id`
  - `POST /api/v1/jobs/{job_id}/cancel` — cooperatively cancel a `pending` or `running` job
  - `POST /api/v1/harmonize` — synchronous harmonization run returning `ProcessingResult` (`507` on quota exceeded, `413` on object/job/temp cap exceeded, `409` on immutability violation, `503`/`502`/`422` on provider errors)
  - `GET /api/v1/datasets` and `GET /api/v1/datasets/{dataset_id}` — browse canonical dataset metadata (`product_version`, `granule_id`, quality coverage; internal `file://`/`s3://`/host asset URIs are redacted, exposing `storage_key` & `zone`)
  - `GET /api/v1/datasets/{dataset_id}/provenance` — retrieve sanitized dataset provenance (`local://` basename redaction) and storage asset references
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
- External access & admin security: `EARTHDATA_TOKEN`, `MODIS_ENABLED` (`true`), `GPM_ENABLED` (`true`), `SMAP_ENABLED` (`true`), `NASA_POWER_ENABLED` (`true`), `EARTHDATA_PRESIGNED_HOSTS` (`*.cloudfront.net,*.amazonaws.com`), `CMR_BASE_URL`, `NASA_POWER_BASE_URL`, `GENERIC_HANDLER_ALLOWED_HOSTS` (default empty = `GenericHandler` disabled), `GHS_ADMIN_TOKEN` (required for `/api/v1/storage/reconcile` and `/cleanup`; returns `503` if unset)
- HTTP & Worker resilience: `HTTP_TIMEOUT_SECONDS` (`30`), `HTTP_MAX_RETRIES` (`3`), `HTTP_RETRY_BACKOFF_SECONDS` (`1`), `HTTP_MAX_DOWNLOAD_BYTES` (`2147483648`), `WORKER_POLL_INTERVAL_SECONDS` (`2`), `WORKER_LEASE_SECONDS` (`300`), `MAX_GRID_PIXELS` (`100000000`)

Run PostgreSQL schema migrations before starting production instances:

```bash
cd backend/services/geospatial_harmonization
uv run alembic upgrade head
```

## Running Locally & Docker

From the repository root you can also use `make dev-ghs` (API + worker together), `make ghs-api-dev`, `make ghs-worker-dev`, `make ghs-migrate`, `make ghs-test`, and `make ghs-lint`.

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

To execute opt-in live NASA provider smoke tests (`tests/live/test_nasa_live_smoke.py`), set `RUN_LIVE_NASA_TESTS=1` (and `EARTHDATA_TOKEN` with an Earthdata Login User Token for protected DAAC granule downloads):

```bash
RUN_LIVE_NASA_TESTS=1 uv run pytest -m live -v
```

## Verified Dependency Notes

- Verified on `x86_64-manylinux_2_28` with Python `3.13.16`: `rasterio` (`1.5.2`), `pyhdf` (`0.11.7`), `h5py`, `netCDF4`, `pyproj`, `shapely`, `xarray`, `rioxarray`, and `zarr` install from prebuilt binary wheels without compilation on Debian Bookworm (`python:3.13-slim-bookworm`).
