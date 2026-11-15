# PROJECT TERRA — Scientific Core Technical Specification (`terra-scientific`)

**Package:** `terra-scientific` (`backend/scientific/`)  
**Version:** `0.1.0`  
**Integration:** Imported cleanly by `terra-core` (`backend/core/`) and `terra-worker` (`backend/worker/`), consuming prepared dataset payloads mapped from GHS (`backend/services/geospatial_harmonization/`) without pulling heavy native GDAL/HDF dependencies into `terra-core`.

---

## 1. Architectural Boundaries

```text
GHS (HTTP DatasetOut / Manifest) ──► terra_scientific.adapters.ghs ──► ScientificDataset / GridStack
                                                                              │
Core API / terra-worker ────────────► AssessmentRequest ────────────► ScientificAssessmentService
                                                                              │
                                                                    ScientificAssessmentResult
                                                                     + ProvenanceTrace (SHA-256)
                                                                     + JSON Artifacts (manifest)
```

- **Pure Numerical Core (`numpy`, `pandas`, `scipy`, `pydantic`):** All statistical, temporal, and spatial algorithms execute deterministically with zero coupling to FastAPI, SQLAlchemy, HTTP clients, UI components, or LLMs.
- **Optional Geospatial Extra (`terra-scientific[geospatial]`):** GeoTIFF reading (`rasterio`, `xarray`, `rioxarray`, `shapely`, `pyproj`) is isolated in optional extras; runtime NumPy `.npz` archives load safely with `allow_pickle=False`.
- **Execution Separation:** Heavy NumPy/SciPy computations are dispatched off Core's ASGI event loop via `asyncio.to_thread(...)` in `AssessmentApplicationService` or asynchronously by `AssessmentWorkerRunner` (`terra-worker`) using `claim_next_queued()` (`FOR UPDATE SKIP LOCKED` on PostgreSQL, atomic conditional update on SQLite).

---

## 2. Package Layout (`backend/scientific/src/terra_scientific/`)

- `domain/` — `enums.py`, `exceptions.py`, `contracts.py` (`DatasetLoaderPort`, `ArtifactWriterPort`), and typed Pydantic models (`models/temporal.py`, `models/quality.py`, `models/dataset.py`, `models/provenance.py`, `models/request.py`, `models/result.py`).
- `sources/catalog.py` — Authoritative product metadata, physical valid ranges, fill values, native CRS definitions (including MODIS Sinusoidal WKT/PROJ4), QA policies, and explicit `assert_quantitative_source_allowed` guard against `nasa_gibs`.
- `methods/registry.py` — `DEFAULT_METHOD_REGISTRY` versioning every implemented P0/P1 method and explicitly flagging P2 methods (`implemented=False`).
- `adapters/ghs.py` — `map_ghs_dataset_payload` (`DatasetOut` JSON to `ScientificDataset`) and `LocalArtifactDatasetLoader` (path-traversal guarded JSON / `.npz` / optional GeoTIFF loader).
- `quality/` — Source-specific QA evaluators (`qa_policies.py`) and single-pass fill-mask, scale/offset, valid-range, and QA bitmask validator (`validator.py`).
- `temporal/` — Half-hourly IMERG rate-to-depth integration (`aggregation.py`), calendar/DOY-bin seasonal grouping & Kelvin-to-Celsius conversion (`seasonal.py`), and explicit opt-in gap interpolation (`interpolation.py`).
- `baselines/climatology.py` — Stratified seasonal climatologies (`mean`, `median`, `std`, `1.4826 * MAD`, `IQR`, `Q10`, `Q90`) with assessment-overlap leakage prevention.
- `anomalies/detector.py` — Standardized z-scores, robust MAD z-scores (null-safe when reference dispersion vanishes), rank percentiles, and persistent anomaly episode grouping.
- `trends/` — Exact small-sample ($n \le 10$) permutation + tie-corrected Mann-Kendall (`mann_kendall.py`), Hirsch-Slack Seasonal Mann-Kendall (`seasonal_mk.py`), elapsed-time Theil-Sen slope with Gilbert CI (`sens_slope.py`), lag-k ACF / Ljung-Box $Q$ / Effective Sample Size / Hamed-Rao & Yue-Wang TFPW (`autocorrelation.py`).
- `spatial/` — Area-weighted / $\cos(\phi)$-weighted zonal statistics (`zonal.py`), vectorized row-chunked pixel MK+Sen (`pixel_trends.py`), Benjamini-Hochberg FDR control (`fdr.py`), Queen-8 / Rook-4 Global Moran's $I$ and Local Getis-Ord $G_i^*$ (`autocorrelation.py`), and resolution disparity checks (`support_guard.py`).
- `cross_variable/analysis.py` — Pairwise timestamp alignment, deseasonalization, Pearson $r$ (Fisher-$z$ CI), Spearman $\rho$, lagged cross-correlation, OLS multiple regression with VIF collinearity checks, and partial correlations framed strictly as non-causal associations.
- `disturbances/detector.py` — Recursive Pettitt (1979) structural break detection and persistent negative/positive anomaly episode extraction.
- `recovery/analyzer.py` — Post-disturbance event recovery duration, completeness ratio, elapsed recovery rate, and right-censored tagging (`"incomplete_censored"`).
- `resilience/metrics.py` — Separated `Resistance`, `Recovery`, `Stability`, and `Sensitivity` dimensions alongside explicitly withheld `CompositeTriStatus(status="unavailable_unvalidated", value=None)`.
- `uncertainty/assessor.py` — Three-tier uncertainty synthesis (`data_quality`, `statistical`, `scientific`) including autocorrelation sensitivity checks (Hamed-Rao vs standard MK).
- `pipeline/` — `ScientificAssessmentService` (`service.py`) orchestrating all P0/P1 stages with partial-dataset fault tolerance and SHA-256 input digest tracking, plus `JsonArtifactWriter` (`artifacts.py`).

---

## 3. Data Sources, Units, & QA Policies

| Product / ID | Resolution & Grid | Temporal Cadence & Semantics | Physical Units & Scaling | Implemented QA & Scientific Rules |
| :--- | :--- | :--- | :--- | :--- |
| **`MOD13Q1.061`** (`modis_mod13q1`) | 250 m · MODIS Sinusoidal | 16-day `COMPOSITE` | `NDVI`, `EVI` (`dimensionless`, raw scale `0.0001`, fill `-3000`, valid `[-0.2, 1.0]`) | `pixel_reliability` (`0`=Good, `1`=Marginal accepted under `STANDARD`; clouds/snow/fill excluded) + 16-bit `VI_Quality` MODLAND/usefulness/cloud/shadow/snow bits; NDVI/EVI analyzed separately; 16-day DOY-bin seasonal grouping preserved |
| **`MOD11A2.061`** (`modis_mod11a2`) | 1000 m · MODIS Sinusoidal | 8-day `COMPOSITE` | `LST_Day_1km`, `LST_Night_1km` (`K`, raw scale `0.02`, fill `0`, valid `[150, 380] K`; optional `K -> degC` helper `- 273.15`) | 8-bit `QC_Day`/`QC_Night` mandatory QA (bits 0-1) and LST error (bits 6-7) enforced; Day & Night kept independent; radiometric skin temperature limitation noted |
| **`GPM_3IMERGHH.07` / `.06`** (`gpm_imerg`) | ~11.1 km (`0.1°`) · `EPSG:4326` | 30-min `INTERVAL` | V07 `Grid/precipitation` (V06 `precipitationCal`) in `mm/hr` (`[0, 400]`, fills `-9999.9`, `-9999.0`) | Rate-to-depth integration: $\text{depth}_{\text{mm}} = \text{rate}_{\text{mm/hr}} \times 0.5\text{ hr}$; missing intervals remain `NaN` (never 0 mm) and coverage ratio is checked; `Final` run required by default (`Early`/`Late` blocked unless explicitly opted in); `precipitationQualityIndex` threshold checked when present |
| **`SPL3SMP_E.006`** (`smap_spl3smp_e`) | 9 km posting / ~36 km native footprint · EASE-Grid 2.0 (`EPSG:6933`) | Daily `COMPOSITE` | `soil_moisture` / `soil_moisture_pm` in `cm^3/cm^3` (`[0.02, 0.65]`, fill `-9999.0`) | `retrieval_qual_flag` bit 0 (`0`/`8` accepted in `STANDARD`) and `surface_flag` (blocks frozen/snow/water); **AM (~06:00) and PM (~18:00) overpasses separated by default** (`smap_overpass_mode="am_only"`); senses top 0-5 cm only |
| **`POWER_DAILY` (`v10`)** (`nasa_power`) | Coarse reanalysis: `MERRA-2` (`0.5°×0.625°`), `CERES SYN1deg` (`1.0°×1.0°`) · `EPSG:4326` | Daily `INTERVAL` | `T2M`/`T2M_MAX`/`T2M_MIN` (`degC`), `RH2M` (`%`), `PRECTOTCORR` (`mm/day`), `ALLSKY_SFC_SW_DWN` (`MJ/m^2/day`), `WS2M` (`m/s`), `GWETTOP` (`dimensionless`), fill `-999.0` | Enforces physical bounds & coverage fraction; preserves MERRA-2 vs CERES origin metadata; guards against silently pairing coarse `PRECTOTCORR` alongside GPM IMERG (`allow_power_precip_with_gpm=False`) |
| **`NASA GIBS`** (`nasa_gibs`) | Web tiles | Contextual browse only | **Prohibited** | **Hard rejected** (`gibs_quantitative_prohibited` -> Core HTTP `422`) in `sources/catalog.py`, `adapters/ghs.py`, `quality/validator.py`, and Core API pre-validation |

**Core Invariants:**
- **Single-scale guarantee:** `scale_factor` and `add_offset` are applied ONLY after fill masking and ONLY when `VariableMetadata.is_scaled=False`, preventing double scaling if upstream GHS already scaled values.
- **Intensive vs. Extensive Aggregation:** `aggregate_temporal_series` prohibits summing `CONTINUOUS_INTENSIVE` variables (`NDVI`, `EVI`, `LST`, `soil_moisture`, `T2M`) across time; `CONTINUOUS_EXTENSIVE` depths (`precipitation_accumulation_mm`) use `SUM` with missing-coverage thresholds instead of silent zero-filling.

---

## 4. Scientific Methodology & Implementation Status (P0 / P1 / P2)

### P0 — Scientific Foundation (Implemented & Tested)

1. **`qa_screening` (`1.0.0`):** Fill masking, idempotent scaling, physical range filtering, product-specific bitmask QA (`STRICT`, `STANDARD`, `PERMISSIVE`), and valid-fraction sufficiency checking.
2. **`imerg_rate_to_depth` (`1.0.0`):** Converts valid half-hourly IMERG rates ($\text{mm/hr} \times 0.5$) into daily/monthly precipitation accumulations (`mm`) tracking expected vs valid interval counts.
3. **`climatology_baseline` (`1.0.0`):** Stratified reference mean, median, standard deviation, scaled MAD ($1.4826 \cdot \text{MAD}$), IQR, and Q10/Q90 (`fixed_reference`, `out_of_sample`, `cross_validated`, or `full_period_explicit` requiring `allow_explicit_full_period=True`). Enforces `exclude_assessment_overlap=True` when assessment timestamps overlap a fixed baseline.
4. **`anomaly_detection` (`1.0.0`):** Computes parametric $z = (x - \mu)/\sigma$, robust $z_r = (x - \text{med})/(1.4826 \cdot \text{MAD})$, empirical rank percentiles, and persistent runs above/below `zscore_threshold` (default `1.5`) and `min_persistence_steps` (default `2`). Zero-dispersion bins yield `None` instead of `inf`/`NaN`.
5. **`mann_kendall` (`1.0.0`) & `sens_slope` (`1.0.0`):**
   - Mann-Kendall $S = \sum_{i<j}\operatorname{sgn}(x_j - x_i)$ with exact dynamic-programming permutation $p$-value for $n \le 10$ and tie-corrected normal approximation $Z_c$ for $n > 10$.
   - Theil-Sen slope median over actual elapsed time $\Delta t$ (years by default) + Gilbert $1-\alpha$ nonparametric confidence interval.
6. **`seasonal_mann_kendall` (`1.0.0`):** Hirsch-Slack stratified MK ($\sum_g S_g$, $\sum_g \text{Var}(S_g)$) preserving calendar-month or 16-day MODIS DOY strata without pooling seasonal amplitude into trends.
7. **`autocorrelation_diagnostics` (`1.0.0`):** Lag-1 and multi-lag ACF on detrended residuals, Ljung-Box $Q$ statistic, effective sample size $N_{\text{eff}}$, and opt-in autocorrelation-adjusted inference (`hamed_rao` variance inflation or `yue_wang_tfpw` trend-free pre-whitening; default policy is `diagnostic_only`).
8. **`spatial_zonal_stats` (`1.0.0`):** Projected cell-area or $\cos(\text{latitude})$ weighted spatial averages, medians, dispersion, and valid-pixel coverage tracking over 3D grid stacks $(T, Y, X)$.

### P1 — Ecological & Spatial Analysis (Implemented & Tested)

9. **`benjamini_hochberg_fdr` (`1.1.0`):** Step-up Benjamini-Hochberg adjusted $q$-values across valid pixel tests (`compute_chunked_pixel_trends` chunking rows in memory-bounded blocks; benchmarked $64 \times 64 \times 30$ grids well under 3s).
10. **`spatial_autocorrelation` (`1.0.0`):** Global Moran's $I$ (permutation pseudo-$p$) and Local Getis-Ord $G_i^*$ hotspot/coldspot $z$-scores over valid pixel footprints.
11. **`cross_variable_association` (`1.0.0`):** Common-timestamp inner alignment, deseasonalization (`deseasonalize=True`), Pearson $r$ (Fisher-$z$ 95% CI), Spearman $\rho$, lagged cross-correlation (`max_lag_steps`), OLS multiple regression with Variance Inflation Factor (VIF) multicollinearity diagnostics, and partial correlation. Automatically warns on spatial resolution disparities and enforces non-causal wording.
12. **`pettitt_change_point` (`1.0.0`):** Pettitt (1979) non-parametric Mann-Whitney two-sample shift statistic $K_T = \max_t |U_{t,T}|$ with recursive significant segment splitting and persistent disturbance episode grouping.
13. **`event_recovery` (`1.0.0`):** Pre-disturbance baseline mean, trough magnitude, elapsed recovery duration, completeness ratio $(x_{\text{end/rec}} - x_{\text{peak}})/(x_{\text{pre}} - x_{\text{peak}})$, recovery rate, and `"incomplete_censored"` labeling when series ends before `recovery_fraction_threshold` (default `0.9`).
14. **`resilience_dimensions` (`1.0.0`):** Reports four unpooled proxy dimensions:
    - **Resistance:** $1 / (1 + \max|z_{\text{peak}}|)$ when disturbance occurs.
    - **Recovery:** Mean completeness fraction across post-event recovery episodes.
    - **Stability:** $1 / (1 + s(\text{deseasonalized residuals}))$ when $\ge 6$ valid residuals exist.
    - **Sensitivity:** OLS response-anomaly slope per driver anomaly unit (labeled non-causal).

### P2 — Explicitly Deferred / Withheld

The following capabilities remain `implemented=False` in `DEFAULT_METHOD_REGISTRY` and are never fabricated at runtime:

- **`composite_tri` (`0.0.0-unvalidated`):** Any `ResilienceMetricsResult` returns `composite_tri=CompositeTriStatus(status="unavailable_unvalidated", available=False, value=None, rationale=...)`; weighted composite index output is withheld until empirically calibrated against reference drought/disturbance benchmarks.
- **`critical_slowing_down` (`0.0.0-deferred`):** Rolling AR(1) and variance early-warning indicators require equidistant high-frequency continuous series without composite gap artifacts.
- **`causal_attribution` (`0.0.0-deferred`):** Observational cross-variable correlations and regressions cannot establish causal attribution without explicit causal identification.

---

## 5. Verification Commands

- Scientific Core standalone: `make scientific-test`, `make scientific-lint` (Ruff + strict `mypy src`).
- Core Backend (includes `/api/v1/assessments*` API, ownership, GIBS rejection, mock GHS mapping, artifact bounds): `make backend-test`, `make backend-lint`.
- Shared Worker (`terra-worker` claiming queued assessments + failure isolation): `make worker-test`, `make worker-lint`.
- OpenAPI & Frontend TypeScript contract sync: `make contracts`.
