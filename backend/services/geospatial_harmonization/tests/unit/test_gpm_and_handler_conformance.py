"""Unit tests for GPMIMERGHandler and cross-provider handler conformance."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import h5py
import netCDF4
import numpy as np
import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.config import Settings
from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    ProviderDisabledError,
    QualityPolicyViolationError,
)
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.domain.ports import DataHandler
from geospatial_harmonization.handlers import (
    GPMIMERGHandler,
    build_default_handler_registry,
)
from geospatial_harmonization.handlers.gpm_imerg import accumulate_imerg_rates
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


def _imerg_v07_hdf5_bytes(tmp_path: Path, *, bad_units: str = "mm/hr") -> bytes:
    p = tmp_path / "3B-HHR.MS.MRG.3IMERG.20260710-S120000-E122959.0720.V07B.HDF5"
    with h5py.File(p, "w") as h5f:
        h5f.attrs["GranuleID"] = "3B-HHR.MS.MRG.3IMERG.20260710-S120000-E122959.0720.V07B.HDF5"
        grid = h5f.create_group("Grid")
        lon = grid.create_dataset("lon", data=np.array([-60.05, -59.95], dtype=np.float32))
        lon.attrs["units"] = b"degrees_east"
        lat = grid.create_dataset("lat", data=np.array([-10.05, -9.95], dtype=np.float32))
        lat.attrs["units"] = b"degrees_north"

        precip = grid.create_dataset(
            "precipitation",
            data=np.array([[[8.0, -9999.9], [-2.0, 4.0]]], dtype=np.float32),
        )
        precip.attrs["DimensionNames"] = b"time,lon,lat"
        precip.attrs["units"] = bad_units.encode("ascii")
        precip.attrs["_FillValue"] = np.float32(-9999.9)

        pqi = grid.create_dataset(
            "precipitationQualityIndex",
            data=np.array([[[0.85, -9999.9], [0.5, 0.1]]], dtype=np.float32),
        )
        pqi.attrs["DimensionNames"] = b"time,lon,lat"
        pqi.attrs["_FillValue"] = np.float32(-9999.9)

        liq = grid.create_dataset(
            "probabilityLiquidPrecipitation",
            data=np.array([[[100, -1], [100, 90]]], dtype=np.int16),
        )
        liq.attrs["DimensionNames"] = b"time,lon,lat"
        liq.attrs["_FillValue"] = np.int16(-1)
    return p.read_bytes()


async def test_gpm_imerg_v07_hdf5_grouped_qa_accumulation_and_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.30", 443))],
    )
    h5_bytes = _imerg_v07_hdf5_bytes(tmp_path)

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {
                            "id": "G555-GESDISC",
                            "producer_granule_id": (
                                "3B-HHR.MS.MRG.3IMERG.20260710-S120000-E122959.0720.V07B.HDF5"
                            ),
                            "time_start": "2026-07-10T12:00:00.000Z",
                            "time_end": "2026-07-10T12:29:59.999Z",
                            "links": [
                                {
                                    "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                                    "href": "https://data.gesdisc.earthdata.nasa.gov/3B-HHR.HDF5",
                                }
                            ],
                        }
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        return Response(200, content=h5_bytes)

    handler = GPMIMERGHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw_h5",
        transport=MockTransport(handle_http),
    )
    ds = await handler.handle_payload(
        {"product": "GPM_3IMERGHH.07", "start_time": datetime(2026, 7, 10, 12, 0, tzinfo=UTC)}
    )
    assert ds.granule_id == "3B-HHR.MS.MRG.3IMERG.20260710-S120000-E122959.0720.V07B.HDF5"
    assert ds.product_version == "07"
    assert ds.spatial_metadata.spatial_resolution == "0.1 deg (~10 km)"
    # Valid: (8.0, 4.0) -> depth 4.0 and 2.0 mm (mean 3.0 mm); fill & negative excluded
    assert ds.quality_metadata.valid_observation_fraction == pytest.approx(0.5)
    assert ds.quality_metadata.exclusion_breakdown["fill_nodata"] == 1
    assert ds.quality_metadata.exclusion_breakdown["out_of_range"] == 1
    assert ds.extensions["interval_depth_mean_mm"] == pytest.approx(3.0, abs=1e-4)
    assert ds.extensions["low_pqi_pixel_count"] == 1
    assert ds.extensions["mean_liquid_precip_probability_pct"] == pytest.approx(96.6666, abs=1e-2)

    # Multi-interval accumulation (2 half-hour intervals -> mm depth)
    w1 = TemporalSpec(
        datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        datetime(2026, 7, 10, 12, 30, tzinfo=UTC),
        "30min",
        "interval",
    )
    w2 = TemporalSpec(
        datetime(2026, 7, 10, 12, 30, tzinfo=UTC),
        datetime(2026, 7, 10, 13, 0, tzinfo=UTC),
        "30min",
        "interval",
    )
    accum = accumulate_imerg_rates(
        [np.array([[10.0, -9999.9]], dtype=np.float32), np.array([[4.0, 2.0]], dtype=np.float32)],
        [w1, w2],
        min_coverage_fraction=1.0,
    )
    assert float(accum.data[0, 0]) == pytest.approx(7.0)
    assert np.isnan(accum.data[0, 1])
    assert float(accum.coverage_fraction[0, 1]) == pytest.approx(0.5)

    # Reject incompatible accumulated unit ("mm") mislabeled as half-hour rate
    bad_unit_bytes = _imerg_v07_hdf5_bytes(tmp_path, bad_units="mm")
    bad_handler = GPMIMERGHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw_bad_units",
        transport=MockTransport(lambda _r: Response(200, content=bad_unit_bytes)),
    )
    with pytest.raises(QualityPolicyViolationError, match="precipitation rate"):
        await bad_handler.handle_payload(
            {
                "product": "GPM_3IMERGHH.07",
                "granule_url": "https://data.gesdisc.earthdata.nasa.gov/bad.HDF5",
                "start_time": datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
            }
        )

    disabled = GPMIMERGHandler(
        settings=Settings(_env_file=None, environment="test", gpm_enabled=False),
        raw_dir=tmp_path / "raw_disabled",
        transport=MockTransport(handle_http),
    )
    with pytest.raises(ProviderDisabledError):
        await disabled.handle_payload(
            {"product": "GPM_3IMERGHH.07", "start_time": datetime(2026, 7, 10, 12, 0, tzinfo=UTC)}
        )
