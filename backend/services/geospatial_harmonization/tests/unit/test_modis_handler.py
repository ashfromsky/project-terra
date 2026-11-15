"""Unit tests for MODISHandler Sinusoidal CRS, composites, and QA separation."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from httpx import MockTransport, Request, Response
from pyhdf.SD import SD, SDC

from geospatial_harmonization.config import Settings
from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    ProviderDisabledError,
)
from geospatial_harmonization.domain.ports import DataHandler
from geospatial_harmonization.handlers import MODISHandler
from geospatial_harmonization.handlers.modis import (
    MODIS_SINUSOIDAL_WKT,
    decode_mod11a2_qc,
    decode_mod13q1_pixel_reliability,
    decode_mod13q1_vi_quality,
)


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


def test_modis_bitmask_decoders_identify_clouds_snow_shadow_and_lst_qc() -> None:
    pr = decode_mod13q1_pixel_reliability(np.array([-1, 0, 1, 2, 3, 9], dtype=np.int8))
    assert pr["qa_fill"].tolist() == [True, False, False, False, False, False]
    assert pr["good"].tolist() == [False, True, False, False, False, False]
    assert pr["marginal"].tolist() == [False, False, True, False, False, False]
    assert pr["snow_ice"].tolist() == [False, False, False, True, False, False]
    assert pr["cloudy"].tolist() == [False, False, False, False, True, False]
    assert pr["qa_unrecognized"].tolist() == [False, False, False, False, False, True]

    # bits: 0=good, 2=MODLAND cloud, 3=not_produced, (1<<8)=adj cloud, (1<<10)=mixed cloud,
    # (1<<14)=snow, (1<<15)=shadow, (15<<2)=lowest usefulness
    vi = decode_mod13q1_vi_quality(
        np.array([0, 2, 3, 1 << 8, 1 << 10, 1 << 14, 1 << 15, 15 << 2], dtype=np.uint16)
    )
    assert vi["cloudy"].tolist() == [False, True, False, True, True, False, False, False]
    assert vi["not_produced"].tolist() == [False, False, True, False, False, False, False, False]
    assert vi["snow_ice"].tolist() == [False, False, False, False, False, True, False, False]
    assert vi["shadow"].tolist() == [False, False, False, False, False, False, True, False]
    assert vi["low_usefulness"].tolist() == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
    ]

    qc = decode_mod11a2_qc(
        np.array([0b00000000, 0b00000010, 0b00000011, 0b11000000], dtype=np.uint8)
    )
    assert qc["cloudy"].tolist() == [False, True, False, False]
    assert qc["not_produced"].tolist() == [False, False, True, False]
    assert qc["high_lst_error"].tolist() == [False, False, False, True]


def _modis_qa_hdf4_bytes(
    hdf_path: Path,
    ndvi_vals: list[list[int]],
    vi_qa_vals: list[list[int]],
    reliability_vals: list[list[int]],
) -> bytes:
    hdf_path.unlink(missing_ok=True)
    sd = SD(str(hdf_path), SDC.WRITE | SDC.CREATE)
    try:
        ndvi = sd.create("250m 16 days NDVI", SDC.INT16, (2, 2))
        ndvi[:, :] = np.array(ndvi_vals, dtype=np.int16)
        ndvi.attr("_FillValue").set(SDC.INT16, -3000)
        ndvi.endaccess()

        qa = sd.create("250m 16 days VI Quality", SDC.UINT16, (2, 2))
        qa[:, :] = np.array(vi_qa_vals, dtype=np.uint16)
        qa.endaccess()

        pr = sd.create("250m 16 days pixel reliability", SDC.INT8, (2, 2))
        pr[:, :] = np.array(reliability_vals, dtype=np.int8)
        pr.endaccess()

        sd.attr("LOCALGRANULEID").set(SDC.CHAR, "MOD13Q1.A2026152.h12v10.061.2026170000001.hdf")
        sd.attr("StructMetadata.0").set(
            SDC.CHAR,
            (
                "GROUP=GridStructure\n"
                "  GROUP=GRID_1\n"
                "    XDim=2\n    YDim=2\n"
                "    UpperLeftPointMtrs=(0.0,1000.0)\n"
                "    LowerRightMtrs=(500.0,500.0)\n"
                "    Projection=GCTP_SNSOID\n"
                "  END_GROUP=GRID_1\n"
                "END_GROUP=GridStructure\nEND\n"
            ),
        )
    finally:
        sd.end()
    return hdf_path.read_bytes()


async def test_modis_qa_pixel_rejection_granule_metadata_and_disabled_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.10", 443))],
    )
    # Pixels: valid, out-of-range (-0.25), marginal + VI cloud bit, snow/ice
    hdf_bytes = _modis_qa_hdf4_bytes(
        tmp_path / "good_mixed.hdf",
        ndvi_vals=[[5000, -2500], [6000, 7000]],
        vi_qa_vals=[[0, 0], [1 << 10, 0]],
        reliability_vals=[[0, 0], [1, 2]],
    )

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {
                            "id": "G12345-LPCLOUD",
                            "producer_granule_id": "MOD13Q1.A2026152.h12v10.061.2026170000001.hdf",
                            "time_start": "2026-06-01T00:00:00.000Z",
                            "time_end": "2026-06-16T23:59:59.000Z",
                            "links": [
                                {
                                    "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                                    "href": "https://data.lpdaac.earthdatacloud.nasa.gov/MOD13Q1.hdf",
                                }
                            ],
                        }
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        return Response(200, content=hdf_bytes)

    handler = MODISHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw",
        transport=MockTransport(handle_http),
    )
    ds = await handler.handle_payload(
        {"product": "MOD13Q1.061", "start_time": datetime(2026, 6, 1, tzinfo=UTC)}
    )
    assert ds.granule_id == "MOD13Q1.A2026152.h12v10.061.2026170000001.hdf"
    assert ds.product_version == "061"
    assert ds.spatial_metadata.spatial_resolution == "250 m"
    assert ds.temporal_metadata.end == datetime(2026, 6, 16, 23, 59, 59, tzinfo=UTC)
    assert ds.quality_metadata.valid_observation_fraction == pytest.approx(0.25)
    assert ds.quality_metadata.excluded_count == 3
    assert ds.quality_metadata.exclusion_breakdown["out_of_range"] == 1
    assert ds.quality_metadata.exclusion_breakdown["cloudy"] == 1
    assert ds.quality_metadata.exclusion_breakdown["snow_ice"] == 1

    # All-rejected HDF still preserves explicit 0.0 coverage and flags unreliable observation
    all_bad_bytes = _modis_qa_hdf4_bytes(
        tmp_path / "all_bad.hdf",
        ndvi_vals=[[5000, 5000], [5000, 5000]],
        vi_qa_vals=[[0, 0], [0, 0]],
        reliability_vals=[[3, 3], [3, 3]],
    )
    bad_handler = MODISHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw_bad",
        transport=MockTransport(lambda req: Response(200, content=all_bad_bytes)),
    )
    bad_ds = await bad_handler.handle_payload(
        {
            "product": "MOD13Q1.061",
            "granule_url": "https://data.lpdaac.earthdatacloud.nasa.gov/bad.hdf",
            "start_time": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )
    assert bad_ds.quality_metadata.valid_observation_fraction == 0.0
    assert bad_ds.extensions["unreliable_all_pixels_rejected"] is True
    assert "all_pixels_rejected_by_qa_or_fill" in bad_ds.quality_metadata.exclusion_reasons

    disabled_handler = MODISHandler(
        settings=Settings(_env_file=None, environment="test", modis_enabled=False),
        raw_dir=tmp_path / "raw_dis",
        transport=MockTransport(handle_http),
    )
    with pytest.raises(ProviderDisabledError):
        await disabled_handler.handle_payload(
            {"product": "MOD13Q1.061", "start_time": datetime(2026, 6, 1, tzinfo=UTC)}
        )
