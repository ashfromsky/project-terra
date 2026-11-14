# TERRA Geospatial Harmonization Service

Independent Python service (`geospatial-harmonization` / `geospatial_harmonization`) implementing the Geospatial Harmonization Layer (GHL) for the TERRA platform.

## Verified Dependency & Environment Notes

- **Python / Package Manager:** Python `>=3.13` managed with `uv` (`pyproject.toml` + `uv.lock`).
- **Geospatial Stack (verified on `x86_64-manylinux_2_28`, Python `3.13.16`):**
  - `rasterio` (`1.5.2`, bundled GDAL `3.12.2`): provides `GTiff`, `netCDF`, `HDF5`, `HDF5Image`; **does not** bundle GDAL `HDF4`.
  - `pyhdf` (`0.11.7`): ships prebuilt manylinux wheels for Python 3.13 and handles HDF4 Scientific Data Set decoding directly without system headers. Source builds or Alpine/non-manylinux targets require system `libhdf4` (`libhdf4-dev` / `hdf4`) and `libgdal-dev`.
  - `rioxarray`, `xarray`, `pyproj`, `shapely`, `h5py`, `netCDF4`, `zarr` (v3), `numpy`, `pandas`.
- **Configuration:** All settings and secrets are declared in [`Settings`](src/geospatial_harmonization/config/settings.py) via `pydantic-settings`. Per repository ADR 0001, no `.env*` files are committed.

## Development Commands

```bash
cd backend/services/geospatial_harmonization
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
