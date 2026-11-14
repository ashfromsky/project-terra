# GHS ADR 0001 — Handlers, Canonical Contracts, and Readers

- **Status:** Accepted
- **Date:** 2026-11-14
- **Scope:** `geospatial_harmonization.handlers`, `geospatial_harmonization.readers`, `geospatial_harmonization.domain`.

## Decisions

1. **Handler-per-provider boundary.** External APIs (`MODISHandler`, `GPMIMERGHandler`, `SMAPHandler`, `NASAPowerHandler`) register via `HandlerRegistry` with independent Pydantic input models. Handlers own API transport, auth, pagination, and provider metadata mapping; they never reimplement reprojection, CRS transforms, or resampling.
2. **Restricted `GenericHandler` with SSRF guards.** `GenericHandler` supports declarative endpoints using an explicit trusted-host allowlist (`GENERIC_HANDLER_ALLOWED_HOSTS`), rejecting private/loopback/link-local IP targets and redirects to disallowed hosts. It never intercepts failures of specialized handlers.
3. **Canonical output contract (`SpatialDataset`).** All handlers emit a canonical dataset envelope (`dataset_id`, `source_id`, `provider`, `product`, `variables`, `units`, `spatial_metadata`, `temporal_metadata`, `quality_metadata`, `assets`, `provenance`, `extensions`) supporting raster, point, and vector representations without discarding provider-specific metadata.
4. **Provider scientific semantics (verified specifications):**
   - **MODIS (`MOD13Q1.061`, `MOD11A2.061`):** Authalic Sinusoidal CRS (`R=6371007.181 m`), product-specific scale factors (`0.0001` NDVI/EVI, `0.02` K LST), fill values, 8/16-day compositing metadata, and strict separation of continuous layers from QA/categorical bitmasks (never scaled or interpolated).
   - **GPM IMERG (`GPM_3IMERGHH` V06/V07):** Resolve spatial axes dynamically from actual dimensions/coordinates rather than hardcoding `(lon, lat)` order; support V07 (`precipitation`) and V06 (`precipitationCal`); integrate interval rates (`mm/hr`) into depth (`mm`) using interval bounds while tracking valid coverage, missing counts, and Early/Late/Final run provenance.
   - **SMAP (`SPL3SMP_E` v006):** Distinguish nominal 9 km EASE-Grid 2.0 spacing (`EPSG:6933`) from the ~36 km native radiometer footprint interpolated via Backus-Gilbert optimal interpolation; preserve AM/PM and global/polar groups; treat `retrieval_qual_flag` values `0` and `8` as recommended quality.
   - **NASA POWER:** Preserve per-variable provenance and native spatial resolution (`0.5° x 0.625°` MERRA-2 for `T2M`/`T2M_MAX`/`T2M_MIN`/`RH2M`/`WS10M` vs. `1.0° x 1.0°` CERES SYN1deg for `ALLSKY_SFC_SW_DWN`) across `point` and `regional` modes.
5. **Format-agnostic `Reader` subsystem.** `ReaderRegistry` selects readers (`HDF4Reader`, `HDF5Reader`, `NetCDFReader`, `GeoTIFFReader`, `ZarrReader`, `JSONReader`, `CSVReader`) using magic-byte/header inspection with extension fallback, decoding lazily into `DecodedDataset` without inventing missing georeferencing.
