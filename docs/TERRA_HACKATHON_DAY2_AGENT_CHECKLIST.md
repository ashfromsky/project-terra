# PROJECT TERRA — Day 2 Execution Checklist

> **Historical Note (2026-11-15):** This Day 2 planning checklist reflects the pre-integration hackathon starting point when `backend/scientific/` was still a placeholder. For the current implemented state (5-process `make dev-full`, `terra-scientific`, Core `data_sources` + `assessments/compare`, GHS multi-granule & `temporal.py` wiring, and connected UI workspaces), see [`docs/PROJECT_OVERVIEW.md`](./PROJECT_OVERVIEW.md) and [`docs/ENVIRONMENT_SETUP.md`](./ENVIRONMENT_SETUP.md).

**Deadline:** Sunday, 15 November 2026, 23:59 (local event time, Europe/Kyiv)  
**Working start:** 09:00  
**Primary goal:** deliver one scientifically credible, reproducible end-to-end Earth System Trend Detective workflow — not the entire long-term TERRA architecture.

---

## 0. Mission and scope freeze

- [ ] Read the repository `AGENTS.md`, `docs/PROJECT_OVERVIEW.md`, relevant ADRs, and the GHS README before changing code.
- [ ] Confirm the current `main` state and run `git status`; preserve all existing user changes.
- [ ] Verify the new `make dev`, `make dev-ghs`, and `make dev-full` orchestration before relying on them.
- [ ] Confirm all four processes start and stop cleanly: Frontend, Core, GHS API, GHS Worker.
- [ ] Confirm the real current state: `backend/scientific/` is still a placeholder; GHS is implemented but not integrated into Core/Frontend; some map overlays and overview/assessment pages still use synthetic/demo values.
- [ ] Agree on one demonstration AOI, one NASA product, one analysis period, and one primary question. Do not expand the scope after this decision without an explicit blocker.
- [ ] Keep a visible distinction between `REAL DATA`, `SYNTHETIC DATA`, `PREVIEW`, and `UNAVAILABLE` throughout the UI and documentation.

**Non-goal:** do not attempt to finish every planned layer, every resilience metric, every service, or full global pixel-level analytics in one day.

## 1. P0 — Prove one real data path (Data / GHS Agent)

**Objective:** obtain and process a real NASA Earth-observation product for a bounded AOI.

- [ ] Verify the existing `MODISHandler` path for `MOD13Q1.061` against the current code and official product documentation.
- [ ] Verify Earthdata/CMR access and credentials without exposing tokens in logs or committed files.
- [ ] Retrieve at least one actual MOD13Q1 granule intersecting the selected AOI. Prefer a small, manageable AOI and bounded date range.
- [ ] Decode the actual HDF4 product through the existing ReaderRegistry.
- [ ] Apply the product's documented scale factor, nodata handling, and QA screening. Verify the exact QA bit policy from authoritative MOD13Q1 documentation; do not invent bit masks.
- [ ] Preserve source product/version, granule ID, acquisition/composite dates, units, native CRS/grid, QA policy, retrieval time, and processing parameters.
- [ ] Clip/window the raster to the selected AOI without claiming that resampling increases source resolution.
- [ ] Produce an AOI-level observation summary with valid-pixel count, valid fraction, missing/QA-masked fraction, and NDVI statistic.
- [ ] Persist raw and derived assets through the existing GHS storage interfaces (`raw/`, `intermediate/`, `derived/`) and verify read-back plus checksums/provenance.
- [ ] Verify that storage quota/ledger behavior does not break this path. Use local storage for the demo unless R2/S3 credentials and connectivity are already verified.
- [ ] Record the exact command, environment variables required, product/granule identifiers, and any access limitations.

**Acceptance criteria:** at least one real granule is decoded, QA-screened, clipped to the chosen AOI, summarized, persisted, and read back. A mocked response or synthetic raster does not satisfy this criterion.

**Fallback if NASA access blocks the run:** use a legally accessible, verifiable real sample granule already available to the project; disclose its date, source, and spatial limits. Do not relabel synthetic data as real.

## 2. P0 — Implement a small, testable Scientific Service (Scientific Agent)

**Objective:** implement only the numerical methods needed for the selected demonstration.

- [ ] Create the minimal pure-Python package under `backend/scientific/` following the accepted architecture: no FastAPI, SQLAlchemy, network, storage, or frontend dependencies in scientific algorithms.
- [ ] Define typed input/output models for an irregularly sampled or missing-value time series, units, timestamps, method/version, and quality/coverage metadata.
- [ ] Implement a reproducible AOI time-series aggregation contract (or consume the verified AOI series from the Data/GHS Agent); preserve observation counts and missing periods.
- [ ] Implement the anomaly/baseline method only if a defensible baseline and sufficient observations are available. Document the baseline window and seasonal treatment.
- [ ] Implement Mann–Kendall and Sen's slope with tie handling, missing-value handling, output units, sample count, and a clear significance interpretation.
- [ ] Explicitly assess temporal seasonality and autocorrelation. Do not present a naive p-value as fully corrected for autocorrelation. Either use a justified method or label/document the limitation.
- [ ] Return `insufficient_data` / `not_assessed` when sample size, coverage, or baseline requirements are not met. Do not fabricate a trend or confidence interval.
- [ ] Add deterministic tests with known monotonic, no-trend, tied, missing-observation, and insufficient-data series.
- [ ] Add a reproducible example/notebook or fixture showing the input observations and exact output.
- [ ] Document every method, assumption, unit, limitation, and reference used.

**Acceptance criteria:** unit tests pass; an independently runnable scientific function returns a trend result for a verified observation series, or an explicit insufficient-data result. The output is reproducible and does not overstate significance.

**Do not implement tomorrow:** a universal TRI, arbitrary weighted resilience score, AI-derived scientific numbers, or every planned ecological metric.

## 3. P0 — Minimal Core ↔ GHS ↔ Scientific integration (Integration Agent)

**Objective:** connect the smallest useful vertical slice without redesigning the system.

- [ ] Inspect the actual GHS API, job lifecycle, dataset metadata, storage references, Core dependency wiring, and existing service boundaries.
- [ ] Propose a minimal, explicit integration contract before coding. Keep GHS independently runnable and preserve ADR-0002.
- [ ] Define the smallest workflow needed to submit/track a MODIS processing task and obtain its persisted dataset/result metadata.
- [ ] Ensure long-running retrieval/processing stays in GHS Worker jobs; do not hold an HTTP request open for a long raster job.
- [ ] Connect the processed AOI series to the Scientific Service through a typed application-level contract.
- [ ] Expose only the minimum API needed by the selected UI workflow. Generate frontend types from OpenAPI; do not hand-edit generated contracts.
- [ ] Propagate job state, data coverage, source provenance, QA summary, and explicit error/insufficient-data states.
- [ ] Add focused tests for the integration contract, failure paths, and one end-to-end local flow.
- [ ] If integration is too risky to complete, provide a clearly documented runnable scientific pipeline and do not fake the Core/GHS connection.

**Acceptance criteria:** the chosen AOI/product can be processed through a real, repeatable path and the scientific result can be traced back to source observations. Any remaining manual step is documented honestly.

## 4. P0 — Global map and regional drill-down (Frontend Agent)

**Objective:** make the global experience convincing while accurately representing data coverage and resolution.

- [ ] Preserve the existing Equal Earth / Globe / Mercator map architecture and NASA GIBS integration.
- [ ] Make global navigation smooth: pan, zoom, projection choice, layer selection, and clear layer attribution.
- [ ] Use NASA GIBS WMTS for contextual imagery/browse visualization where supported; treat tile loading as map tile streaming, not as a scientific data feed.
- [ ] Add or finish a clear global-to-regional drill-down: global view → selected region/AOI → available product/time range → analytical detail.
- [ ] Display per-layer availability, native resolution, temporal cadence, coverage period, and data-source attribution from the backend catalog.
- [ ] Do not promise detailed scientific coverage at every zoom level. Respect the selected product's actual spatial resolution, temporal cadence, archive, and missing-data limitations.
- [ ] Clearly distinguish a GIBS browse tile from a quantitatively processed MODIS observation.
- [ ] Replace synthetic analytical overlays in the selected demonstration path with the real output from the backend, or visibly label them as synthetic previews and disable scientific interpretation for them.
- [ ] Add an AOI analysis panel with: selected area, product, period, time series, trend estimate, significance, valid-observation coverage, QA/missing-data disclosure, and provenance.
- [ ] Include loading, job-running, failed, no-data, and insufficient-data states.
- [ ] Avoid a new visual redesign. Reuse the existing Figma-derived design system and shared components.

**Acceptance criteria:** a judge can start from the world map, select the demonstration AOI, inspect a truthful data layer, and reach the real scientific result without mistaking synthetic previews for observations.

## 5. P1 — Storage and database checks (Infrastructure Agent)

**Objective:** use the infrastructure already implemented instead of building duplicate infrastructure.

- [ ] Verify GHS storage governance on the selected real data path: quota reservation, asset persistence, checksum, deduplication where relevant, and read-back.
- [ ] Verify local storage works reproducibly for the judging/demo environment.
- [ ] Use R2/S3 only if credentials, bucket, permissions, and upload/read-back are already available and tested.
- [ ] Use PostgreSQL only if it is already configured and materially required for the real workflow or a meaningful concurrency verification.
- [ ] Run the existing GHS Alembic migrations explicitly when required; do not drop/reset existing databases.
- [ ] Run the PostgreSQL `SKIP LOCKED` / quota reservation integration tests only when a real test database is available; report skipped tests honestly.
- [ ] Do not add PgBouncer for the hackathon demo.
- [ ] Do not add PostGIS merely to match the target architecture. Add it only if the selected workflow actually needs spatial SQL beyond the current geometry handling, and only if there is time to configure and verify it.
- [ ] Do not create a second object store, second storage ledger, or duplicate job queue.

**Acceptance criteria:** the selected real observation/result survives persistence and can be retrieved with provenance. No unnecessary infrastructure is introduced.

## 6. P1 — Final scientific presentation and demo (Narrative / QA Agent)

- [ ] Write a concise project summary tied directly to the `Be An Earth System Trend Detective!` challenge.
- [ ] State the scientific question, selected variable, NASA product, AOI, analysis period, method, and result.
- [ ] Explain what is changing, where, by how much, and whether the detected trend is statistically significant (or why significance could not be assessed).
- [ ] Explain QA screening, observation coverage, missing data, spatial/temporal resolution, and methodological limitations.
- [ ] Provide direct source references to NASA product documentation and data access pages.
- [ ] Prepare a 2–3 minute demo script: world map → AOI selection → data/product information → time series → trend result → provenance/limitations.
- [ ] Capture screenshots or a short recording of the actual running application, not static mockups presented as live functionality.
- [ ] Update root README and `docs/PROJECT_OVERVIEW.md` to match what is actually implemented today.
- [ ] Disclose any synthetic, cached, precomputed, or manually prepared data used in the demo.
- [ ] Verify project submission fields, project link, demo link, AI-use disclosure, team information, and NASA data citations before submitting.

## 7. Suggested schedule (Kyiv time)

| Time | Focus | Exit condition |
|---|---|---|
| 09:00–09:45 | Baseline, full-stack startup, scope freeze | All processes start/stop; one AOI/product chosen |
| 09:45–12:30 | Real MODIS data path + Scientific Service in parallel | Real observation series available; algorithm tests pass |
| 12:30–13:00 | Integration checkpoint | Decide whether full API/UI integration is still feasible |
| 13:00–15:30 | Core/GHS/Scientific vertical slice | One reproducible processing-to-analysis path |
| 15:30–17:30 | Global map + AOI drill-down | User can reach the real result from the map |
| 17:30–18:00 | Feature freeze | No new features after this point |
| 18:00–20:00 | Regression, data/provenance audit, UI states | No fake scientific claims; demo path works |
| 20:00–21:30 | README, challenge narrative, screenshots/demo | Submission materials complete |
| 21:30–23:00 | Full rehearsal and final fixes | Demo rehearsed; critical blockers resolved |
| 23:00–23:59 | Submit and verify submission | Submission confirmed before deadline |

**If the schedule slips:** protect the verified data → scientific result → clear map-to-result demo → submission. Drop secondary features before weakening scientific validity.

## 8. Agent coordination and engineering rules

- [ ] Assign separate ownership: Data/GHS, Scientific, Integration/API, Frontend, Narrative/QA.
- [ ] Avoid multiple agents editing the same files simultaneously. Use separate worktrees/branches when available; the project owner handles integration.
- [ ] Every agent must inspect `git status` first and preserve pre-existing changes.
- [ ] Follow the repository's 300–400 changed-source-line review target per increment, without splitting cohesive work artificially.
- [ ] Agents must stop after each reviewable increment, inspect the complete diff, run relevant checks, and request owner review.
- [ ] No agent may merge branches, rebase, cherry-pick, force-push, amend, or push unapproved work.
- [ ] Do not report tests/builds/integrations as passing unless actually executed.
- [ ] Every handoff must include: modified files, source-line additions/deletions, commands run, exact test results, skipped checks, known limitations, and next blocker.
- [ ] The owner prioritizes and reviews; agents do not independently expand the scope.

## 9. Explicitly out of scope for this deadline

- [ ] PgBouncer.
- [ ] A new message broker or another worker service.
- [ ] A second Data Lake / storage implementation.
- [ ] Full PostGIS adoption unless a demonstrated spatial query requires it.
- [ ] HLS integration as an additional product source.
- [ ] Full global, per-pixel, multi-product, multi-decadal analytics.
- [ ] Fully validated TERRA Resilience Index (TRI) or arbitrary resilience weights.
- [ ] AI fine-tuning for scientific calculations or trend detection.
- [ ] New infrastructure that does not directly enable the selected demo workflow.

## 10. Definition of Done

- [ ] The demo starts from the actual application, not a slide or a standalone notebook alone.
- [ ] The user can inspect the globe/global map and select a real AOI.
- [ ] At least one real NASA Earth-observation product is used and its product/version/date are disclosed.
- [ ] The AOI time series is derived from decoded observations with documented scale, QA, and missing-data handling.
- [ ] Mann–Kendall and Sen's slope (or a clearly justified subset) produce reproducible, tested results with honest limitations.
- [ ] The map/UI displays coverage, resolution, method, provenance, and significance state without misleading claims.
- [ ] Any remaining synthetic/demo content is explicitly labeled.
- [ ] Tests and verification results are recorded honestly.
- [ ] README, project overview, demo narrative, and submission fields match the actual implementation.
- [ ] The project is submitted before 23:59 local time and submission confirmation is checked.

**Final principle:** ship one scientifically trustworthy, end-to-end result. Do not trade scientific validity for breadth, streaming buzzwords, or infrastructure completeness.
