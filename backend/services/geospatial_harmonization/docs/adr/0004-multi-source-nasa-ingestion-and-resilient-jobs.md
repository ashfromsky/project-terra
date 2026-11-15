# GHS ADR 0004 — Multi-Source NASA Ingestion Security, Provenance, and Resilient Jobs

- **Status:** Accepted
- **Date:** 2026-11-15
- **Scope:** `geospatial_harmonization.config`, `geospatial_harmonization.handlers`, `geospatial_harmonization.worker`, `geospatial_harmonization.api`, `geospatial_harmonization.infrastructure`.

## Context

Integrating MODIS (`MOD13Q1.061`, `MOD11A2.061`), GPM IMERG (`GPM_3IMERGHH`), SMAP (`SPL3SMP_E.006`), and NASA POWER requires provider-specific authentication flows, cross-host DAAC → Earthdata URS → CloudFront/S3 redirects, strict preservation of physical units and QA bitmasks, non-secret API exposure, and resilient background job retries.

## Decisions

1. **Provider isolation & token scoping.**
   - `Settings` exposes per-provider flags (`MODIS_ENABLED`, `GPM_ENABLED`, `SMAP_ENABLED`, `NASA_POWER_ENABLED`) alongside `EARTHDATA_TOKEN` (`SecretStr`).
   - `NASA POWER` requests and public `CMR` metadata discovery never receive `EARTHDATA_TOKEN`.
   - Protected DAAC downloads follow redirects explicitly via `safe_fetch_bytes` / `safe_fetch_to_file` without automatic `follow_redirects=True`: Bearer tokens are sent only on trusted Earthdata/URS hosts, URS session cookies stay scoped to authenticated session hops without forwarding Bearer headers to untrusted hosts, and presigned CloudFront/S3 URLs are permitted only against validated `EARTHDATA_PRESIGNED_HOSTS` without auth headers.
   - SSRF checks validate schemes (`https`/`http` per callsite; HTTPS enforced for live DAAC & CMR hops) and reject loopback/private/link-local resolved IP addresses. `GenericHandler` remains disabled when `GENERIC_HANDLER_ALLOWED_HOSTS` is empty.
2. **Scientific provenance & quality preservation in `SpatialDataset`.**
   - `SpatialDataset` records `product_version`, `granule_id`, `TemporalSpec.acquisition_timestamp`, `QualityMetadata.valid_observation_fraction`, `missing_data_fraction`, `quality_flags_applied`, and `exclusion_breakdown`.
   - MODIS QA bitmasks, GPM IMERG `precipitationQualityIndex` and rate-to-depth separation, SMAP `retrieval_qual_flag` (`0`/`8` recommended) and frozen/snow/water `surface_flag` masks, and NASA POWER multi-resolution (`MERRA-2` vs. `CERES SYN1deg`) metadata are explicitly decoded without treating missing/fill pixels as zero.
3. **API redaction & discovery surface.**
   - API schemas (`AssetOut`, `DatasetProvenanceOut`, `ProviderStatusOut`) omit secrets and redact internal storage URIs (`file://`, `s3://`, host paths) while preserving `storage_key` and `zone`.
   - `/api/v1/providers` and `POST /api/v1/discover` expose non-secret catalog metadata and CMR/POWER observation discovery without storing intermediate artifacts.
4. **Resilient worker orchestration (Alembic `0003_job_retry_and_idempotency`).**
   - `ghs_harmonization_jobs` adds `error_category`, `next_retry_at`, `progress_pct`, and `idempotency_key`.
   - `WorkerRunner` classifies errors via `classify_exception`: non-retryable auth, authorization, validation, or quota/security failures transition directly to `failed`, while transient network/rate-limit/5xx errors reschedule with bounded exponential backoff (`next_retry_at`, capped at 3600 s). Cancelled jobs cannot be overwritten on completion, and duplicate `idempotency_key` submissions reuse active/succeeded jobs unless `allow_duplicate=true`.
