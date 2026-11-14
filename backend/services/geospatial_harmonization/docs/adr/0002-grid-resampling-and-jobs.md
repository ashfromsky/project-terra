# GHS ADR 0002 — GridSpec, TargetGridTransformer, and Job Persistence

- **Status:** Accepted
- **Date:** 2026-11-14
- **Scope:** `geospatial_harmonization.domain`, `geospatial_harmonization.transformations`, `geospatial_harmonization.infrastructure`.

## Decisions

1. **Explicit, mutually validated `GridSpec`.** `GridSpec` captures target CRS (stored as WKT2/authority code to prevent lossy PROJ4 truncation), X/Y resolutions, resolution units, spatial bounds, width, height, affine transform, alignment policy, and pixel-coordinate convention (`center` vs. `corner`). When dimensions or affine transforms are omitted, `GridSpec` derives them deterministically from bounds, resolution, and alignment without silently mutating caller-supplied parameters.
2. **Independent `TargetGridTransformer`.** `TargetGridTransformer` accepts `TargetGridTransformRequest` and returns `TargetGridTransformResult` with transformation provenance, warnings, and QC reports. It contains zero provider conditionals and operates via windowed/chunked GDAL/Rasterio/Xarray paths without mutating raw source assets.
3. **Semantics-aware resampling policy.** Resampling method selection is driven by variable physical semantics (`intensive` continuous -> `bilinear`/`cubic`, `extensive` flux/accumulation -> quantity-aware `sum`/`average` area conservation, `categorical` & `QA` -> `nearest`/`mode` only). Upsampling records an explicit resolution-fidelity warning and never claims gained native detail.
4. **Storage and job persistence.** Source (`raw/`), harmonized (`intermediate/`), and output (`derived/`) assets persist via a `StoragePort` (`LocalObjectStore` for dev/tests, `S3ObjectStore` via `boto3` for S3-compatible Data Lakes). Operational jobs and metadata reside in service-owned PostgreSQL tables using `FOR UPDATE SKIP LOCKED` lease claiming (`WorkerRunner`), keeping large arrays out of SQL rows. SQLite (`aiosqlite`) supports local unit/repository tests, while PostgreSQL integration tests verify real locking and concurrency semantics.

## Alternatives Considered

- *Single global resampling default (rejected):* corrupts QA bitmasks and non-conserved extensive quantities.
- *Redis/Celery broker (rejected):* violates `SYSTEM_ARCHITECTURE.md` §4.9 by introducing unnecessary infrastructure alongside PostgreSQL.
