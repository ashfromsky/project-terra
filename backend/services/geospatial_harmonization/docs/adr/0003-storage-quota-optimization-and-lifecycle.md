# GHS ADR 0003 — Storage Quota Protection, Optimization, and Lifecycle Governance

- **Status:** Accepted
- **Date:** 2026-11-14
- **Scope:** `geospatial_harmonization.config`, `geospatial_harmonization.domain`, `geospatial_harmonization.storage`, `geospatial_harmonization.readers`, `geospatial_harmonization.transformations`, `geospatial_harmonization.handlers`, `geospatial_harmonization.infrastructure`, `geospatial_harmonization.application`, `geospatial_harmonization.api`, `geospatial_harmonization.worker`.

## Decisions

1. **Transactional Application-Level Storage Ledger & Atomic Quota Reservations (`StorageQuotaManager`).**
   Rather than relying exclusively on eventually consistent provider billing metrics (such as Cloudflare R2 analytics), GHS tracks storage objects, asset ownership references, active reservations, and audit events in PostgreSQL (Alembic revision `0002_storage_ledger`: `ghs_storage_ledger`, `ghs_storage_reservations`, `ghs_storage_objects`, `ghs_storage_asset_refs`, `ghs_storage_audit_events`). Concurrent `reserve_capacity` calls serialize through `SELECT ... FOR UPDATE` on PostgreSQL (with SQLite transaction fallback in local tests). Reservations reserve estimated capacity before object creation, commit actual stored bytes after completion, release unused headroom, and reconcile expired leases safely. Exceeding budget returns HTTP `507 Insufficient Storage` (`StorageBudgetExceededError`); exceeding per-object, per-job-output, or temp-space limits returns HTTP `413 Content Too Large` (`ObjectTooLargeError`).

2. **Three-Zone Object Layout & Source Immutability (`StorageZoneManager`).**
   Object keys partition into `raw/<provider>/<product>/...`, `intermediate/<owner>/...`, and `derived/<product>/...`. Source assets in `raw/` are immutable (overwrite and automatic post-job/TTL/orphan deletion raise `StorageImmutabilityError` / HTTP `409 Conflict`). Temporary files in `intermediate/` carry short configurable retention and are cleaned up when no longer referenced. Unreferenced failed-job derived/intermediate outputs are cleaned immediately upon job failure, whereas published datasets (`ref_kind="dataset"`) and scientific results (`ref_kind="result"`) remain protected.

3. **Scientifically Safe Lossless Compression & Precision Preservation (`DataCompressionManager`).**
   Derived GeoTIFF/COG outputs use lossless `ZSTD` or `DEFLATE` with dtype-appropriate TIFF predictors (`PREDICTOR=3` for float, `PREDICTOR=2` for <=32-bit int), tiling (`512` default), and `BIGTIFF=IF_SAFER`. Helper operations optimize NetCDF (`zlib` + `shuffle`, upgrading `NETCDF3_CLASSIC` only when filter-capable lossless copy runs), Zarr v3 (`zarr.codecs`), and HDF5 (`gzip` + `shuffle`), while leaving source HDF4 untouched and skipping recompression when savings fall below the configured threshold (5% default). Silent `float64 -> float32` downcasting, integer narrowing, quantization, and lossy codecs remain forbidden by `PrecisionPolicy`.

4. **AOI-Aware Windowed Reads & Streaming Transfers.**
   `TargetGridTransformer` decodes source rasters via `WindowedAssetReader` / `GeoTIFFReader.read_windowed`, transforming target AOI bounds cleanly and padding intersection windows instead of materializing unclipped global arrays unnecessarily; `clip_raster_to_aoi` produces non-destructive derived crops. HTTP handlers stream payloads chunk-by-chunk directly to staging files with SHA-256 verification and byte-cap enforcement (`safe_fetch_to_file`), while `S3ObjectStore` / `LocalObjectStore` stream multipart/chunked uploads and downloads (`put_file_stream`, `stream_to_path`) and clean up `.ghs-tmp-*.part` leftovers and abandoned multipart uploads.

5. **Content-Addressed Deduplication & Grace-Protected Lifecycle (`ContentDeduplicationService`, `StorageLifecycleManager`).**
   Identical binary files (computed via streaming SHA-256) in deduplicatable zones (`raw`, `derived`) reuse existing stored binaries while recording separate `AssetReferenceLink` provenance rows per dataset/product/job. `StorageLifecycleManager` executes mark-and-sweep cleanup honoring orphan grace periods, active job/dataset/result locks, dry-run simulation, temp cleanup, and ledger-to-store drift reconciliation. Mutating admin routes (`POST /api/v1/storage/reconcile`, `POST /api/v1/storage/cleanup`) fail closed when `GHS_ADMIN_TOKEN` is unset (HTTP `503`) and enforce constant-time token verification (`401`/`403`) without leaking secrets on `/api/v1/storage/policy` or `/health`.

6. **Bounded Worker Concurrency & Temp Capacity Guards.**
   `WorkerRunner` limits concurrent active jobs with `asyncio.Semaphore(ghs_storage_max_worker_concurrency)`, reconciles expired reservations and storage lifecycle periodically, and cleans handler-created temporary directories upon completion or failure. `HarmonizationService` enforces `ghs_storage_temp_max_bytes` and available disk space before allocating scratch space.

## Alternatives Considered

- *Polling provider storage usage APIs alone (rejected):* Subject to reporting lag and TOCTOU races under concurrent jobs, making strict 8 GB quota protection below R2's 10 GB free tier unreliable.
- *Automatic float64-to-float32 downcasting (rejected):* Compromises numerical precision of scientific coordinates and analytical indicators without explicit domain authorization.
- *Immediate deletion of unreferenced objects without grace periods (rejected):* Risks race conditions against in-flight registrations or external inspection workflows; two-phase mark-and-sweep provides safe recoverability.
