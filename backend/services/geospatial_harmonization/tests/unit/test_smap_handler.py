"""Unit tests for SMAP SPL3SMP_E handler: EASE-Grid 2.0, 36 km footprint, and QA 0/8."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.domain.ports import DataHandler
from geospatial_harmonization.handlers import SMAPHandler


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
