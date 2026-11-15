"""Unit tests for SMAP SPL3SMP_E handler: EASE-Grid 2.0, 36 km footprint, and QA 0/8."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.config import Settings
from geospatial_harmonization.domain.exceptions import ProviderDisabledError
from geospatial_harmonization.domain.ports import DataHandler
from geospatial_harmonization.handlers import SMAPHandler
from geospatial_harmonization.handlers.smap import decode_smap_surface_flag


def _smap_h5_bytes(tmp_path: Path) -> bytes:
    p = tmp_path / "SMAP_SPL3SMP_E.h5"
    with h5py.File(p, "w") as f:
        am = f.create_group("Soil_Moisture_Retrieval_Data_AM")
        sm = am.create_dataset("soil_moisture", data=np.full((2, 2), 0.28, dtype=np.float32))
        sm.attrs["_FillValue"] = np.float32(-9999.0)
        sm.attrs["units"] = "cm^3/cm^3"
        qf = am.create_dataset(
            "retrieval_qual_flag", data=np.array([[0, 8], [1, 16]], dtype=np.uint16)
        )
        qf.attrs["_FillValue"] = np.uint16(65535)
    return p.read_bytes()


async def test_smap_handler_distinguishes_footprint_and_evaluates_qa_0_and_8(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.20", 443))],
    )
    h5_bytes = _smap_h5_bytes(tmp_path)

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {"links": [{"href": "https://n5eil01u.ecs.nsidc.org/SMAP_SPL3SMP_E.h5"}]}
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        return Response(200, content=h5_bytes)

    handler: DataHandler = SMAPHandler(
        raw_dir=tmp_path / "raw", transport=MockTransport(handle_http)
    )
    ds = await handler.handle_payload(
        {"overpass": "AM", "domain": "global", "start_time": datetime(2026, 7, 5, tzinfo=UTC)}
    )
    assert ds.provider == "smap"
    assert ds.spatial_metadata.crs == "EPSG:6933"
    assert ds.extensions["nominal_grid_spacing_m"] == 9000
    assert ds.extensions["native_footprint_km"] == 36.0
    assert any("Backus-Gilbert" in n for n in ds.provenance.notes)
    assert ds.quality_metadata.valid_observation_fraction == pytest.approx(0.5)
    assert ds.quality_metadata.excluded_count == 2
    assert any("retrieval_qual_flag" in k for k in ds.variables)


def test_smap_surface_flag_decoder_identifies_frozen_snow_and_water() -> None:
    # 0=clear, (1<<0)=water, (1<<5)=snow, (1<<7)=rad frozen, (1<<8)=model frozen, 65535=fill
    sf = np.array([0, 1 << 0, 1 << 5, 1 << 7, 1 << 8, 65535], dtype=np.uint16)
    decoded = decode_smap_surface_flag(sf)
    assert decoded["water_body"].tolist() == [False, True, False, False, False, False]
    assert decoded["snow_ice"].tolist() == [False, False, True, False, False, False]
    assert decoded["frozen_ground"].tolist() == [False, False, False, True, True, False]


async def test_smap_pm_overpass_frozen_ground_exclusion_and_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.20", 443))],
    )
    h5_path = tmp_path / "SMAP_L3_PM.h5"
    with h5py.File(h5_path, "w") as f:
        f.attrs["GranuleID"] = "SMAP_L3_SM_P_E_20260705_R19240_001.h5"
        pm = f.create_group("Soil_Moisture_Retrieval_Data_PM")
        sm = pm.create_dataset(
            "soil_moisture_pm",
            # [0,0]=0.22 good, [0,1]=-9999.0 unavailable, [1,0]=0.15 frozen, [1,1]=0.30 skipped
            data=np.array([[0.22, -9999.0], [0.15, 0.30]], dtype=np.float32),
        )
        sm.attrs["_FillValue"] = np.float32(-9999.0)
        sm.attrs["units"] = "cm^3/cm^3"
        qf = pm.create_dataset(
            "retrieval_qual_flag_pm",
            data=np.array([[0, 65535], [8, 2]], dtype=np.uint16),
        )
        qf.attrs["_FillValue"] = np.uint16(65535)
        sf = pm.create_dataset(
            "surface_flag_pm",
            data=np.array([[0, 0], [1 << 8, 0]], dtype=np.uint16),
        )
        sf.attrs["_FillValue"] = np.uint16(65535)
    h5_bytes = h5_path.read_bytes()

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {
                            "id": "G888-NSIDC",
                            "producer_granule_id": "SMAP_L3_SM_P_E_20260705_R19240_001.h5",
                            "time_start": "2026-07-05T00:00:00.000Z",
                            "time_end": "2026-07-05T23:59:59.000Z",
                            "links": [
                                {
                                    "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                                    "href": "https://data.nsidc.earthdatacloud.nasa.gov/SMAP.h5",
                                }
                            ],
                        }
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        return Response(200, content=h5_bytes)

    handler = SMAPHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw_pm",
        transport=MockTransport(handle_http),
    )
    ds = await handler.handle_payload(
        {"overpass": "PM", "domain": "polar", "start_time": datetime(2026, 7, 5, tzinfo=UTC)}
    )
    assert ds.granule_id == "SMAP_L3_SM_P_E_20260705_R19240_001.h5"
    assert ds.product_version == "006"
    assert ds.spatial_metadata.crs == "EPSG:6931"
    assert ds.spatial_metadata.spatial_resolution is not None
    assert "9 km" in ds.spatial_metadata.spatial_resolution
    assert ds.quality_metadata.valid_observation_fraction == pytest.approx(0.25)
    assert ds.quality_metadata.excluded_count == 3
    assert ds.quality_metadata.exclusion_breakdown["fill_nodata"] == 1
    assert ds.quality_metadata.exclusion_breakdown["frozen_ground"] == 1
    assert ds.quality_metadata.exclusion_breakdown["retrieval_skipped"] == 1

    disabled = SMAPHandler(
        settings=Settings(_env_file=None, environment="test", smap_enabled=False),
        raw_dir=tmp_path / "raw_disabled",
        transport=MockTransport(handle_http),
    )
    with pytest.raises(ProviderDisabledError):
        await disabled.handle_payload({"start_time": datetime(2026, 7, 5, tzinfo=UTC)})
