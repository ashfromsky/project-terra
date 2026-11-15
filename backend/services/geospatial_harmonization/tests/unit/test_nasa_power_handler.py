"""Unit tests for NASAPowerHandler point/regional parsing and native resolution provenance."""

import json
import socket
from pathlib import Path

import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.config import Settings
from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    ProviderDisabledError,
    ProviderValidationError,
)
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


async def test_nasa_power_hourly_no_earthdata_auth_and_null_handling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("129.164.179.22", 443))],
    )
    seen_auth: list[str | None] = []

    def handle_http(request: Request) -> Response:
        seen_auth.append(request.headers.get("authorization"))
        doc = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-42.0, -10.0, 400.0]},
            "header": {"fill_value": -999.0, "api": {"version": "v2.6"}},
            "parameters": {
                "PRECTOTCORR": {"units": "mm/hour"},
                "ALLSKY_SFC_SW_DWN": {"units": "MJ/hr"},
            },
            "properties": {
                "parameter": {
                    "PRECTOTCORR": {"2026070100": 1.2, "2026070101": None},
                    "ALLSKY_SFC_SW_DWN": {"2026070100": 0.0, "2026070101": -999.0},
                }
            },
        }
        return Response(200, content=json.dumps(doc).encode("utf-8"))

    settings = Settings(
        _env_file=None,
        environment="test",
        earthdata_token="must-never-leak-to-power",
    )
    handler = NASAPowerHandler(
        settings=settings, raw_dir=tmp_path, transport=MockTransport(handle_http)
    )
    ds = await handler.handle_payload(
        {
            "product": "power_hourly",
            "mode": "point",
            "temporal": "hourly",
            "parameters": ("PRECTOTCORR", "ALLSKY_SFC_SW_DWN"),
            "start_date": "2026-07-01",
            "end_date": "2026-07-01",
            "latitude": -10.0,
            "longitude": -42.0,
        }
    )
    assert seen_auth == [None]
    assert ds.units["PRECTOTCORR"] == "mm/hour"
    assert ds.units["ALLSKY_SFC_SW_DWN"] == "MJ/hr"
    assert ds.variables["PRECTOTCORR"].attributes["supports_rate_to_depth"] is True
    assert ds.temporal_metadata.cadence == "1h"
    assert ds.quality_metadata.exclusion_breakdown == {"fill_nodata": 1, "missing_null": 1}
    assert ds.quality_metadata.valid_observation_fraction == pytest.approx(0.5)


async def test_nasa_power_regional_auto_batch_span_guard_and_422_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("129.164.179.22", 443))],
    )
    requested_params: list[str] = []

    def handle_http(request: Request) -> Response:
        if "BAD_PARAM" in request.url.params.get("parameters", ""):
            return Response(
                422,
                content=json.dumps({"messages": ["Invalid parameter BAD_PARAM"]}).encode("utf-8"),
            )
        p = request.url.params["parameters"]
        requested_params.append(p)
        val = 25.0 if p == "T2M" else 1.5
        doc = {
            "type": "FeatureCollection",
            "header": {"fill_value": -999.0, "api": {"version": "v2.6"}, "sources": ["MERRA2"]},
            "parameters": {p: {"units": "C" if p == "T2M" else "mm/day"}},
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-42.0, -10.5, 450.0]},
                    "properties": {"parameter": {p: {"20260701": val}}},
                }
            ],
        }
        return Response(200, content=json.dumps(doc).encode("utf-8"))

    handler = NASAPowerHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path,
        transport=MockTransport(handle_http),
    )

    with pytest.raises(ProviderValidationError, match=r"2\.0 degree"):
        await handler.handle_payload(
            {
                "mode": "regional",
                "parameters": ("T2M",),
                "start_date": "2026-07-01",
                "end_date": "2026-07-01",
                "min_lat": -11.0,
                "max_lat": -10.5,
                "min_lon": -42.0,
                "max_lon": -41.5,
            }
        )

    merged_ds = await handler.handle_payload(
        {
            "mode": "regional",
            "parameters": ("T2M", "PRECTOTCORR"),
            "start_date": "2026-07-01",
            "end_date": "2026-07-01",
            "min_lat": -12.0,
            "max_lat": -10.0,
            "min_lon": -43.0,
            "max_lon": -41.0,
        }
    )
    assert requested_params == ["T2M", "PRECTOTCORR"]
    assert merged_ds.spatial_metadata.point_count == 1
    assert merged_ds.provenance.source_metadata["batched_requests"] == 2
    assert set(merged_ds.variables) == {"T2M", "PRECTOTCORR"}

    with pytest.raises(ProviderValidationError, match="Invalid parameter BAD_PARAM"):
        await handler.handle_payload(
            {
                "mode": "point",
                "parameters": ("BAD_PARAM",),
                "start_date": "2026-07-01",
                "end_date": "2026-07-01",
                "latitude": -10.0,
                "longitude": -42.0,
            }
        )

    disabled = NASAPowerHandler(
        settings=Settings(_env_file=None, environment="test", nasa_power_enabled=False),
        raw_dir=tmp_path / "dis",
        transport=MockTransport(handle_http),
    )
    with pytest.raises(ProviderDisabledError):
        await disabled.handle_payload(
            {
                "mode": "point",
                "parameters": ("T2M",),
                "start_date": "2026-07-01",
                "end_date": "2026-07-01",
                "latitude": -10.0,
                "longitude": -42.0,
            }
        )


async def test_nasa_power_auto_mode_and_time_series_extraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("129.164.179.22", 443))],
    )
    seen_paths: list[str] = []

    def handle_http(request: Request) -> Response:
        seen_paths.append(request.url.path)
        param = request.url.params["parameters"]
        if "regional" in request.url.path:
            doc = {
                "type": "FeatureCollection",
                "header": {"fill_value": -999.0, "api": {"version": "v2.6"}},
                "parameters": {param: {"units": "C" if param == "T2M" else "mm/day"}},
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-42.5, -10.5, 400.0]},
                        "properties": {
                            "parameter": {
                                param: {"20260701": 20.0, "20260702": 22.0},
                            }
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-41.5, -11.5, 420.0]},
                        "properties": {
                            "parameter": {
                                param: {"20260701": 24.0, "20260702": -999.0},
                            }
                        },
                    },
                ],
            }
            return Response(200, content=json.dumps(doc).encode("utf-8"))
        doc = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-42.0, -10.5, 410.0]},
            "header": {"fill_value": -999.0, "api": {"version": "v2.6"}},
            "parameters": {param: {"units": "C"}},
            "properties": {"parameter": {param: {"20260701": 21.0, "20260702": 23.0}}},
        }
        return Response(200, content=json.dumps(doc).encode("utf-8"))

    handler = NASAPowerHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path,
        transport=MockTransport(handle_http),
    )

    regional_ds = await handler.handle_payload(
        {
            "mode": "auto",
            "parameters": ("T2M", "PRECTOTCORR"),
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-02T23:59:59Z",
            "bbox": [-43.5, -12.5, -41.0, -10.0],
        }
    )
    assert any("regional" in path for path in seen_paths)
    ts_t2m = regional_ds.extensions["time_series"]["T2M"]
    assert ts_t2m["values"] == [pytest.approx(22.0), pytest.approx(22.0)]
    assert ts_t2m["is_scaled"] is True
    assert len(ts_t2m["timestamps"]) == 2
    assert regional_ds.extensions["ingestion_summary"]["mode"] == "regional"

    seen_paths.clear()
    point_ds = await handler.handle_payload(
        {
            "mode": "auto",
            "parameters": ("T2M",),
            "start_date": "2026-07-01",
            "end_date": "2026-07-02",
            "bbox": [-42.2, -10.7, -41.8, -10.3],
        }
    )
    assert any("point" in path for path in seen_paths)
    assert point_ds.extensions["time_series"]["T2M"]["values"] == [21.0, 23.0]
    assert point_ds.extensions["ingestion_summary"]["mode"] == "point"
