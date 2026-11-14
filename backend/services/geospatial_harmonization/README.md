# TERRA Geospatial Harmonization Service

Independent Python service (`geospatial-harmonization` / `geospatial_harmonization`, container image `terra-geospatial-harmonization`) implementing source-agnostic geospatial retrieval, format decoding, semantics-aware grid transformation, quality verification, and durable async execution for TERRA.

## Architecture

Layered modular structure (`api -> application -> domain <- infrastructure`):

- `domain/`: Pure grid (`GridSpec`, `SpatialBounds`, `AffineMatrix`), temporal (`TemporalSpec`), dataset (`SpatialDataset`, `DecodedDataset`), resampling policy (`ResamplingPolicy`), and `Protocol` ports (`DataHandler`, `AssetReader`, `GridTransformer`, `StoragePort`, `JobRepository`, `DatasetRepository`).
- `readers/`: Format-agnostic decoders (`GeoTIFFReader`, `NetCDFReader`, `HDF5Reader`, `HDF4Reader`, `ZarrReader`, `JSONReader`, `CSVReader`) and magic-byte/extension `ReaderRegistry`.
- `transformations/`: Provider-agnostic `TargetGridTransformer` (Rasterio/GDAL warp, center-to-corner affine adjustment), temporal rate-to-depth integration (`integrate_rate_to_depth`), and `QualityValidator`.
- `handlers/`: Retrieval and canonicalization (`MODISHandler`, `GPMIMERGHandler`, `SMAPHandler`, `NASAPowerHandler`, SSRF-guarded `GenericHandler`) registered in `HandlerRegistry`.
- `application/`: `HarmonizationService` end-to-end orchestration use case.
- `infrastructure/`: `LocalObjectStore`, `S3ObjectStore`, SQLAlchemy async models (`ghs_datasets`, `ghs_assets`, `ghs_harmonization_jobs`), PostgreSQL `FOR UPDATE SKIP LOCKED` job repository, and Alembic migrations (`ghs_alembic_version`).
- `api/` & `worker/`: FastAPI ASGI app (`geospatial_harmonization.main:app`) served by Granian and standalone polling `WorkerRunner` (`python -m geospatial_harmonization.worker`).

## Endpoints

- Operational probes: `GET /health`, `GET /ready`, `GET {API_V1_PREFIX}/health`, `GET {API_V1_PREFIX}/ready` (default prefix `/api/v1`)
- Business API (`/api/v1`):
  - `GET /api/v1/capabilities` — registered provider handlers and readers
  - `POST /api/v1/jobs` — enqueue durable async harmonization job (`202 Accepted`)
  - `GET /api/v1/jobs/{job_id}` — inspect job state and linked `dataset_id`
  - `POST /api/v1/harmonize` — synchronous harmonization run returning `ProcessingResult`
  - `GET /api/v1/datasets` and `GET /api/v1/datasets/{dataset_id}` — browse canonical dataset metadata

## Configuration & Migrations

All runtime settings are defined via `pydantic-settings` in [`Settings`](src/geospatial_harmonization/config/settings.py) (`.env*` files are never committed per ADR 0001):

- Database: `DATABASE_URL` (`sqlite+aiosqlite:///./ghs.db` default; use `postgresql+asyncpg://...` in production)
- Storage: `STORAGE_BACKEND` (`local` or `s3`), `LOCAL_STORAGE_DIR`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`
- External access: `EARTHDATA_TOKEN`, `GENERIC_HANDLER_ALLOWED_HOSTS` (default empty = `GenericHandler` disabled)

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
