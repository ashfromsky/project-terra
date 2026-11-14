"""Unit tests for MODISHandler Sinusoidal CRS, composites, and QA separation."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from httpx import MockTransport, Request, Response
from pyhdf.SD import SD, SDC

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.ports import DataHandler
from geospatial_harmonization.handlers import MODISHandler
from geospatial_harmonization.handlers.modis import MODIS_SINUSOIDAL_WKT


def _modis_hdf4_bytes(tmp_path: Path) -> bytes:
    hdf = tmp_path / "MOD13Q1.hdf"
    sd = SD(str(hdf), SDC.WRITE | SDC.CREATE)
    try:
        ndvi = sd.create("250m 16 days NDVI", SDC.INT16, (2, 2))
        ndvi[:, :] = np.array([[5000, -3000], [6000, 7000]], dtype=np.int16)
        ndvi.attr("_FillValue").set(SDC.INT16, -3000)
        ndvi.endaccess()

        qa = sd.create("250m 16 days VI Quality", SDC.UINT16, (2, 2))
        qa[:, :] = np.array([[0, 8], [1, 0]], dtype=np.uint16)
        qa.endaccess()

        sd.attr("StructMetadata.0").set(
            SDC.CHAR,
            (
                "GROUP=SwathStructure\nEND_GROUP=SwathStructure\n"
                "GROUP=GridStructure\n"
                "  GROUP=GRID_1\n"
                "    XDim=2\n"
                "    YDim=2\n"
                "    UpperLeftPointMtrs=(0.0,1000.0)\n"
                "    LowerRightMtrs=(500.0,500.0)\n"
                "    Projection=GCTP_SNSOID\n"
                "  END_GROUP=GRID_1\n"
                "END_GROUP=GridStructure\nEND\n"
            ),
        )
    finally:
        sd.end()
    return hdf.read_bytes()


async def test_modis_cmr_lookup_sinusoidal_and_qa_never_scaled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.10", 443))],
    )
    hdf_bytes = _modis_hdf4_bytes(tmp_path)

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {"links": [{"href": "https://ladsweb.modaps.eosdis.nasa.gov/MOD13Q1.hdf"}]}
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        return Response(200, content=hdf_bytes)

    handler: DataHandler = MODISHandler(
        raw_dir=tmp_path / "raw", transport=MockTransport(handle_http)
    )
    ds = await handler.handle_payload(
        {
            "product": "MOD13Q1.061",
            "bbox": (10.0, 45.0, 11.0, 46.0),
            "start_time": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )
    assert ds.provider == "modis"
    assert ds.temporal_metadata.semantics == "composite"
    assert ds.temporal_metadata.composite_days == 16
    assert ds.variables["250m 16 days NDVI"].scale_factor == 0.0001
    assert ds.variables["250m 16 days NDVI"].nodata == -3000
    assert ds.variables["250m 16 days VI Quality"].semantics == "qa_flag"
    assert ds.variables["250m 16 days VI Quality"].scale_factor is None
    assert ds.quality_metadata.valid_observation_fraction == pytest.approx(0.75)
    assert "6371007.181" in (ds.spatial_metadata.crs or "")
    assert "6371007.181" in MODIS_SINUSOIDAL_WKT

    with pytest.raises(IncompatibleDatasetError, match="Invalid handler payload"):
        await handler.handle_payload(
            {"product": "MOD99Z9.061", "start_time": "2026-06-01T00:00:00Z"}
        )
