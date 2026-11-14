"""Unit tests for NASAPowerHandler point/regional parsing and native resolution provenance."""

import json
import socket
from pathlib import Path

import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.ports import DataHandler
from geospatial_harmonization.handlers import NASAPowerHandler


def _power_point_json() -> bytes:
    return json.dumps(
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [30.5, 50.45, 180.0]},
            "header": {"fill_value": -999.0, "api": {"version": "v2.5"}},
            "parameters": {
                "T2M": {"units": "C"},
                "ALLSKY_SFC_SW_DWN": {"units": "MJ/m^2/day"},
            },
            "properties": {
                "parameter": {
                    "T2M": {"20260701": 21.5, "20260702": -999.0},
                    "ALLSKY_SFC_SW_DWN": {"20260701": 18.2, "20260702": 19.0},
                }
            },
        }
    ).encode("utf-8")


async def test_nasa_power_point_and_regional_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("129.164.179.22", 443))],
    )

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("/point"):
            assert request.url.params["time-standard"] == "UTC"
            return Response(200, content=_power_point_json())
        regional_doc = {
            "type": "FeatureCollection",
            "header": {"fill_value": -999.0, "api": {"version": "v2.5"}},
            "features": [
                {"properties": {"parameter": {"PRECTOTCORR": {"20260701": 2.4}}}},
                {"properties": {"parameter": {"PRECTOTCORR": {"20260701": -999.0}}}},
            ],
        }
        return Response(200, content=json.dumps(regional_doc).encode("utf-8"))

    handler: DataHandler = NASAPowerHandler(raw_dir=tmp_path, transport=MockTransport(handle_http))
    point_ds = await handler.handle_payload(
        {
            "mode": "point",
            "parameters": ("T2M", "ALLSKY_SFC_SW_DWN"),
            "start_date": "2026-07-01",
            "end_date": "2026-07-02",
            "latitude": 50.45,
            "longitude": 30.5,
        }
    )
    assert point_ds.spatial_metadata.representation == "point"
    assert point_ds.variables["T2M"].attributes["native_resolution_deg"] == "0.5x0.625"
    assert point_ds.variables["T2M"].attributes["source_product"] == "MERRA-2"
    assert point_ds.variables["ALLSKY_SFC_SW_DWN"].attributes["native_resolution_deg"] == "1.0x1.0"
    assert point_ds.quality_metadata.excluded_count == 1
    assert point_ds.quality_metadata.valid_observation_fraction == pytest.approx(0.75)

    reg_ds = await handler.handle_payload(
        {
            "mode": "regional",
            "parameters": ("PRECTOTCORR",),
            "start_date": "2026-07-01",
            "end_date": "2026-07-01",
            "min_lat": 49.0,
            "max_lat": 51.0,
            "min_lon": 29.0,
            "max_lon": 31.0,
        }
    )
    assert reg_ds.spatial_metadata.representation == "grid_series"
    assert reg_ds.spatial_metadata.point_count == 2
    assert reg_ds.variables["PRECTOTCORR"].semantics == "continuous_extensive"

    with pytest.raises(IncompatibleDatasetError, match="Invalid handler payload"):
        await handler.handle_payload(
            {
                "mode": "point",
                "parameters": ("T2M",),
                "start_date": "2026-07-02",
                "end_date": "2026-07-01",
            }
        )
