# PROJECT TERRA

**Ecosystem Response & Resilience Intelligence**

TERRA is an open-source environmental analysis platform designed to investigate how ecosystems respond to environmental stress, change over time, and recover from disturbances.

The project aims to transform Earth observation data into interpretable environmental insights through remote sensing, time-series analysis, and ecosystem resilience assessment.

> Project status: Early development. Scientific methodologies and analytical capabilities are under active development.

## Overview

Environmental changes such as droughts, heatwaves, and long-term precipitation shifts can significantly affect ecosystems.

TERRA aims to help investigate these processes by combining multiple environmental indicators and analyzing their temporal relationships.

Instead of relying exclusively on vegetation indices or individual satellite observations, TERRA focuses on ecosystem response dynamics.

## Main Objectives

- Detect long-term environmental trends.
- Investigate ecosystem responses to environmental stress.
- Evaluate vegetation resistance and recovery.
- Compare environmental dynamics across geographic regions.
- Identify potential signs of ecosystem vulnerability.
- Present analytical results with transparent data provenance and uncertainty.

## Scientific Approach

TERRA is being designed around several analytical dimensions:

| Dimension | Description |
|---|---|
| Resistance | How well an ecosystem maintains its characteristics during environmental stress. |
| Recovery | How quickly and completely observed indicators return toward their baseline after disturbance. |
| Stability | How much ecosystem indicators fluctuate over time. |
| Sensitivity | How strongly ecosystem indicators respond to environmental changes. |

These dimensions are intended to form the foundation of a future integrated resilience assessment model.

All metrics and aggregation methods require appropriate scientific justification and validation.

## Data Sources

Planned environmental data sources include:

- **NASA MODIS** — vegetation indices (NDVI, EVI) and land surface temperature.
- **NASA GPM IMERG** — precipitation estimates.
- **NASA SMAP** — soil moisture observations.
- **NASA POWER** — meteorological and solar data.

The availability, temporal coverage, spatial resolution, and quality of each dataset will be considered during analysis.

## Technology Stack

### Frontend

- React 19
- TypeScript
- Vite
- MapLibre GL JS
- deck.gl
- Zustand
- TanStack Query
- Apache ECharts

### Backend

- Python
- FastAPI
- Granian
- Pydantic

### Data and Scientific Computing

Planned components include:

- PostgreSQL
- PostGIS
- DuckDB
- NumPy
- SciPy
- Xarray
- Rasterio
- GeoPandas
- PyArrow

### Development

- uv
- Git
- pytest
- Ruff
- ESLint

## Architecture

TERRA is intended to follow a modular architecture with independently runnable frontend and backend components.

The planned system includes:

- Frontend — interactive maps, visualizations, and analytical interfaces.
- Backend — API, application orchestration, and job management.
- Scientific Core — independent scientific calculations and statistical methods.
- Analytical Engine — analytical processing of environmental datasets.
- Worker — asynchronous execution of computationally intensive tasks.
- Data Storage — structured metadata and geospatial data storage.

The initial implementation will prioritize a modular monolith rather than unnecessary distributed infrastructure.

## Scientific Principles

TERRA aims to follow several principles:

1. Reproducibility — analytical results should be reproducible from documented inputs and methods.
2. Data provenance — sources, product versions, processing steps, and retrieval dates should be traceable.
3. Quality awareness — missing observations and satellite quality flags must be considered.
4. Spatial and temporal consistency — datasets with different resolutions and sampling intervals must be appropriately harmonized.
5. Scientific transparency — assumptions, limitations, and uncertainty must be communicated.
6. No unsupported causal claims — statistical relationships alone do not establish causality.

## Project Status

TERRA is currently in its initial development stage.

Planned development stages:

- [ ] Repository and development environment initialization.
- [ ] Frontend and backend foundation.
- [ ] Environmental data ingestion.
- [ ] Geospatial data processing.
- [ ] Time-series analysis.
- [ ] Ecosystem resistance and recovery metrics.
- [ ] Integrated resilience assessment model.
- [ ] Interactive geospatial visualization.
- [ ] Scientific reporting and uncertainty analysis.

## Open Source

TERRA is intended to be an open-source project.

License: Apache License 2.0.

See [LICENSE](LICENSE) for details.

## Disclaimer

TERRA is an experimental environmental analysis project.

Its outputs should not be interpreted as definitive ecological assessments, forecasts, or proof of causal relationships without appropriate scientific validation.

## Acknowledgements

Developed as part of the NASA Space Apps Challenge 2026.

TERRA is an independent project and is not an official NASA product or service.