"""Unit tests for GPMIMERGHandler and cross-provider handler conformance."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np
import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.ports import DataHandler
from geospatial_harmonization.handlers import (
    GPMIMERGHandler,
    build_default_handler_registry,
)
from geospatial_harmonization.transformations import integrate_rate_to_depth


def _imerg_nc_bytes(tmp_path: Path, var_name: str) -> bytes:
    p = tmp_path / f"{var_name}.nc4"
    with netCDF4.Dataset(p, "w") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("lon", 2)
        ds.createDimension("lat", 2)
        ds.crs = "EPSG:4326"
        ds.createVariable("lon", "f8", ("lon",))[:] = np.array([10.05, 10.15])
        ds.createVariable("lat", "f8", ("lat",))[:] = np.array([45.05, 45.15])
        v = ds.createVariable(var_name, "f4", ("time", "lon", "lat"), fill_value=-9999.9)
        v.units = "mm/hr"
        v[:] = np.array([[[10.0, 4.0], [-9999.9, 6.0]]], dtype=np.float32)
    return p.read_bytes()


@pytest.mark.parametrize(
    ("product", "var_name", "fname", "expected_run"),
    [
        ("GPM_3IMERGHH.07", "precipitation", "3B-HHR.MS.MRG.3IMERG.nc4", "Final"),
        ("GPM_3IMERGHH.06", "precipitationCal", "3B-HHR-L.MS.MRG.3IMERG.nc4", "Late"),
    ],
)
async def test_gpm_imerg_v06_v07_and_interval_depth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    product: str,
    var_name: str,
    fname: str,
    expected_run: str,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.30", 443))],
    )
    nc_bytes = _imerg_nc_bytes(tmp_path, var_name)

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {"links": [{"href": f"https://gpm1.gesdisc.eosdis.nasa.gov/{fname}"}]}
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        return Response(200, content=nc_bytes)

    handler: DataHandler = GPMIMERGHandler(
        raw_dir=tmp_path / "raw", transport=MockTransport(handle_http)
    )
    ds = await handler.handle_payload(
        {"product": product, "start_time": datetime(2026, 7, 10, 12, 0, tzinfo=UTC)}
    )
    assert ds.provider == "gpm_imerg"
    assert ds.provenance.run_type == expected_run
    assert ds.variables[var_name].dimensions == ("time", "lon", "lat")
    assert ds.variables[var_name].semantics == "continuous_extensive"
    assert ds.quality_metadata.excluded_count == 1
    assert ds.quality_metadata.valid_observation_fraction == pytest.approx(0.75)
    assert ds.extensions["interval_depth_mean_mm"] == pytest.approx(10.0 / 3.0, abs=1e-4)

    p_arr = np.array([[[10.0, 4.0], [-9999.9, 6.0]]], dtype=np.float32)
    depth = integrate_rate_to_depth(
        [p_arr], [ds.temporal_metadata], ds.temporal_metadata, nodata=-9999.9
    )
    assert float(depth.data[0, 0, 0]) == pytest.approx(5.0)
    assert np.isnan(depth.data[0, 1, 0])


def test_default_handler_registry_capabilities_and_isolation() -> None:
    reg = build_default_handler_registry()
    caps = reg.list_capabilities()
    assert set(caps.keys()) == {"generic", "gpm_imerg", "modis", "nasa_power", "smap"}
    with pytest.raises(IncompatibleDatasetError, match="No handler registered"):
        reg.get("modis", "UNSUPPORTED_PRODUCT")

    handlers_dir = (
        Path(__file__).resolve().parents[2] / "src" / "geospatial_harmonization" / "handlers"
    )
    for py_file in handlers_dir.glob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        assert "rasterio.warp" not in src
        assert "TargetGridTransformer" not in src
