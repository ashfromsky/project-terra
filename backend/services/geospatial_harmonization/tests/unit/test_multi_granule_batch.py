"""Unit tests for bounded multi-granule batch ingestion across NASA handlers."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
import pytest
from httpx import MockTransport, Request, Response
from pyhdf.SD import SD, SDC

from geospatial_harmonization.config import Settings
from geospatial_harmonization.domain.exceptions import (
    ProviderValidationError,
    QualityPolicyViolationError,
)
from geospatial_harmonization.handlers import GPMIMERGHandler, MODISHandler, SMAPHandler


def _make_modis_hdf4(
    path: Path,
    ndvi_grid: np.ndarray,
    reliability_grid: np.ndarray,
    vi_quality_grid: np.ndarray,
) -> bytes:
    sd = SD(str(path), SDC.WRITE | SDC.CREATE)
    try:
        ndvi = sd.create("250m 16 days NDVI", SDC.INT16, ndvi_grid.shape)
        ndvi[:, :] = ndvi_grid.astype(np.int16)
        ndvi.attr("_FillValue").set(SDC.INT16, -3000)
        ndvi.endaccess()

        rel = sd.create("250m 16 days pixel reliability", SDC.INT8, reliability_grid.shape)
        rel[:, :] = reliability_grid.astype(np.int8)
        rel.attr("_FillValue").set(SDC.INT8, -1)
        rel.endaccess()

        qa = sd.create("250m 16 days VI Quality", SDC.UINT16, vi_quality_grid.shape)
        qa[:, :] = vi_quality_grid.astype(np.uint16)
        qa.endaccess()

        sd.attr("StructMetadata.0").set(
            SDC.CHAR,
            (
                "GROUP=SwathStructure\nEND_GROUP=SwathStructure\n"
                "GROUP=GridStructure\n"
                "  GROUP=GRID_1\n"
                f"    XDim={ndvi_grid.shape[1]}\n"
                f"    YDim={ndvi_grid.shape[0]}\n"
                "    UpperLeftPointMtrs=(0.0,1000.0)\n"
                "    LowerRightMtrs=(500.0,500.0)\n"
                "    Projection=GCTP_SNSOID\n"
                "  END_GROUP=GRID_1\n"
                "END_GROUP=GridStructure\nEND\n"
            ),
        )
    finally:
        sd.end()
    return path.read_bytes()


def _make_imerg_hdf5(
    path: Path, precip_grid: np.ndarray, pqi_grid: np.ndarray, run_name: str
) -> bytes:
    with h5py.File(path, "w") as h5f:
        h5f.attrs["GranuleID"] = run_name
        grid = h5f.create_group("Grid")
        lon = grid.create_dataset("lon", data=np.array([-60.05, -59.95], dtype=np.float32))
        lon.attrs["units"] = b"degrees_east"
        lat = grid.create_dataset("lat", data=np.array([-10.05, -9.95], dtype=np.float32))
        lat.attrs["units"] = b"degrees_north"

        precip = grid.create_dataset("precipitation", data=precip_grid.astype(np.float32))
        precip.attrs["DimensionNames"] = b"time,lon,lat"
        precip.attrs["units"] = b"mm/hr"
        precip.attrs["_FillValue"] = np.float32(-9999.9)

        pqi = grid.create_dataset("precipitationQualityIndex", data=pqi_grid.astype(np.float32))
        pqi.attrs["DimensionNames"] = b"time,lon,lat"
        pqi.attrs["_FillValue"] = np.float32(-9999.9)
    return path.read_bytes()


def _make_smap_hdf5(
    path: Path,
    am_val: float,
    am_qf: int,
    pm_val: float,
    pm_qf: int,
) -> bytes:
    with h5py.File(path, "w") as h5f:
        am = h5f.create_group("Soil_Moisture_Retrieval_Data_AM")
        sm_am = am.create_dataset("soil_moisture", data=np.full((2, 2), am_val, dtype=np.float32))
        sm_am.attrs["_FillValue"] = np.float32(-9999.0)
        sm_am.attrs["units"] = "cm^3/cm^3"
        qf_am = am.create_dataset(
            "retrieval_qual_flag", data=np.full((2, 2), am_qf, dtype=np.uint16)
        )
        qf_am.attrs["_FillValue"] = np.uint16(65535)
        sf_am = am.create_dataset("surface_flag", data=np.zeros((2, 2), dtype=np.uint16))
        sf_am.attrs["_FillValue"] = np.uint16(65535)

        pm = h5f.create_group("Soil_Moisture_Retrieval_Data_PM")
        sm_pm = pm.create_dataset(
            "soil_moisture_pm", data=np.full((2, 2), pm_val, dtype=np.float32)
        )
        sm_pm.attrs["_FillValue"] = np.float32(-9999.0)
        sm_pm.attrs["units"] = "cm^3/cm^3"
        qf_pm = pm.create_dataset(
            "retrieval_qual_flag_pm", data=np.full((2, 2), pm_qf, dtype=np.uint16)
        )
        qf_pm.attrs["_FillValue"] = np.uint16(65535)
        sf_pm = pm.create_dataset("surface_flag_pm", data=np.zeros((2, 2), dtype=np.uint16))
        sf_pm.attrs["_FillValue"] = np.uint16(65535)
    return path.read_bytes()


async def test_modis_multi_granule_batch_partial_failure_and_aoi_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.10", 443))],
    )
    g1 = _make_modis_hdf4(
        tmp_path / "mod1.hdf",
        np.array([[4000, 6000], [9000, 9000]]),
        np.array([[0, 0], [0, 0]]),
        np.array([[0, 0], [0, 0]]),
    )
    g2 = _make_modis_hdf4(
        tmp_path / "mod2.hdf",
        np.array([[8000, 8000], [1000, 1000]]),
        np.array([[0, 0], [0, 0]]),
        np.array([[0, 0], [0, 0]]),
    )

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {
                            "id": "G1",
                            "producer_granule_id": "MOD13Q1.A2026001.h18v09.061.hdf",
                            "time_start": "2026-01-01T00:00:00Z",
                            "time_end": "2026-01-17T00:00:00Z",
                            "links": [{"href": "https://e4ftl01.cr.usgs.gov/MOD13Q1_1.hdf"}],
                        },
                        {
                            "id": "G2",
                            "producer_granule_id": "MOD13Q1.A2026017.h18v09.061.hdf",
                            "time_start": "2026-01-17T00:00:00Z",
                            "time_end": "2026-02-02T00:00:00Z",
                            "links": [{"href": "https://e4ftl01.cr.usgs.gov/MOD13Q1_bad.hdf"}],
                        },
                        {
                            "id": "G3",
                            "producer_granule_id": "MOD13Q1.A2026033.h18v09.061.hdf",
                            "time_start": "2026-02-02T00:00:00Z",
                            "time_end": "2026-02-18T00:00:00Z",
                            "links": [{"href": "https://e4ftl01.cr.usgs.gov/MOD13Q1_2.hdf"}],
                        },
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        if request.url.path.endswith("MOD13Q1_bad.hdf"):
            return Response(500, content=b"upstream error")
        if request.url.path.endswith("MOD13Q1_2.hdf"):
            return Response(200, content=g2)
        return Response(200, content=g1)

    handler = MODISHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw",
        transport=MockTransport(handle_http),
    )
    ds = await handler.handle_payload(
        {
            "product": "MOD13Q1.061",
            "start_time": datetime(2026, 1, 1, tzinfo=UTC),
            "end_time": datetime(2026, 2, 18, tzinfo=UTC),
            "bbox": (0.0, 0.0065, 0.01, 0.01),
            "max_granules": 5,
            "max_concurrency": 2,
        }
    )
    summary = ds.extensions["ingestion_summary"]
    assert summary["requested_count"] == 3
    assert summary["succeeded_count"] == 2
    assert summary["failed_count"] == 1
    ndvi_ts = ds.extensions["time_series"]["NDVI"]
    assert ndvi_ts["is_scaled"] is True
    assert ndvi_ts["values"] == [pytest.approx(0.5), pytest.approx(0.8)]
    assert ndvi_ts["qa_layers"]["pixel_reliability"] == [0, 0]

    def handle_all_fail(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            return handle_http(request)
        return Response(404, content=b"missing")

    strict_handler = MODISHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw_strict",
        transport=MockTransport(handle_all_fail),
    )
    with pytest.raises(ProviderValidationError):
        await strict_handler.handle_payload(
            {
                "product": "MOD13Q1.061",
                "start_time": datetime(2026, 1, 1, tzinfo=UTC),
                "end_time": datetime(2026, 2, 18, tzinfo=UTC),
            }
        )


async def test_gpm_imerg_multi_granule_batch_and_mixed_run_type_rejection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.30", 443))],
    )
    h1 = _make_imerg_hdf5(
        tmp_path / "imerg1.HDF5",
        np.array([[[8.0, 20.0], [20.0, 20.0]]]),
        np.array([[[0.9, 0.9], [0.9, 0.9]]]),
        "3B-HHR.MS.MRG.3IMERG.20260710-S000000-E002959.0000.V07B.HDF5",
    )
    h2 = _make_imerg_hdf5(
        tmp_path / "imerg2.HDF5",
        np.array([[[4.0, 20.0], [20.0, 20.0]]]),
        np.array([[[0.7, 0.7], [0.7, 0.7]]]),
        "3B-HHR.MS.MRG.3IMERG.20260710-S003000-E005959.0030.V07B.HDF5",
    )
    h_early = _make_imerg_hdf5(
        tmp_path / "imerg_early.HDF5",
        np.array([[[2.0, 2.0], [2.0, 2.0]]]),
        np.array([[[0.8, 0.8], [0.8, 0.8]]]),
        "3B-HHR-E.MS.MRG.3IMERG.20260710-S010000-E012959.0060.V07B.HDF5",
    )

    h1_id = "3B-HHR.MS.MRG.3IMERG.20260710-S000000-E002959.0000.V07B.HDF5"
    h2_id = "3B-HHR.MS.MRG.3IMERG.20260710-S003000-E005959.0030.V07B.HDF5"

    def handle_good(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {
                            "id": "I1",
                            "producer_granule_id": h1_id,
                            "time_start": "2026-07-10T00:00:00Z",
                            "time_end": "2026-07-10T00:30:00Z",
                            "links": [{"href": "https://gpm1.gesdisc.eosdis.nasa.gov/imerg1.HDF5"}],
                        },
                        {
                            "id": "I2",
                            "producer_granule_id": h2_id,
                            "time_start": "2026-07-10T00:30:00Z",
                            "time_end": "2026-07-10T01:00:00Z",
                            "links": [{"href": "https://gpm1.gesdisc.eosdis.nasa.gov/imerg2.HDF5"}],
                        },
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        if request.url.path.endswith("imerg2.HDF5"):
            return Response(200, content=h2)
        return Response(200, content=h1)

    handler = GPMIMERGHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw_imerg",
        transport=MockTransport(handle_good),
    )
    ds = await handler.handle_payload(
        {
            "product": "GPM_3IMERGHH.07",
            "data_format": "hdf5",
            "start_time": datetime(2026, 7, 10, 0, 0, tzinfo=UTC),
            "end_time": datetime(2026, 7, 10, 1, 0, tzinfo=UTC),
            "bbox": (-60.1, -10.1, -59.99, -9.99),
        }
    )
    precip_ts = ds.extensions["time_series"]["Grid/precipitation"]
    assert precip_ts["values"] == [pytest.approx(8.0), pytest.approx(4.0)]
    assert precip_ts["qa_layers"]["precipitationQualityIndex"] == [
        pytest.approx(0.9, abs=1e-4),
        pytest.approx(0.7, abs=1e-4),
    ]
    assert ds.extensions["accumulated_depth_mm"] == pytest.approx(6.0, abs=1e-4)
    assert ds.extensions["ingestion_summary"]["run_type"] == "Final"

    h_early_id = "3B-HHR-E.MS.MRG.3IMERG.20260710-S010000-E012959.0060.V07B.HDF5"

    def handle_mixed(request: Request) -> Response:
        if request.url.path.endswith(h_early_id):
            return Response(200, content=h_early)
        return Response(200, content=h1)

    mixed_handler = GPMIMERGHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw_mixed",
        transport=MockTransport(handle_mixed),
    )
    with pytest.raises(QualityPolicyViolationError, match="Mixed IMERG run types"):
        await mixed_handler.handle_payload(
            {
                "product": "GPM_3IMERGHH.07",
                "data_format": "hdf5",
                "start_time": datetime(2026, 7, 10, 0, 0, tzinfo=UTC),
                "end_time": datetime(2026, 7, 10, 1, 30, tzinfo=UTC),
                "granule_urls": [
                    f"https://gpm1.gesdisc.eosdis.nasa.gov/{h1_id}",
                    f"https://gpm1.gesdisc.eosdis.nasa.gov/{h_early_id}",
                ],
            }
        )


async def test_smap_multi_granule_overpass_tags_and_time_series(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.107.175.20", 443))],
    )
    s1 = _make_smap_hdf5(tmp_path / "smap1.h5", 0.24, 0, 0.19, 1)
    s2 = _make_smap_hdf5(tmp_path / "smap2.h5", 0.30, 8, 0.21, 0)

    def handle_http(request: Request) -> Response:
        if request.url.path.endswith("granules.json"):
            cmr = {
                "feed": {
                    "entry": [
                        {
                            "id": "S1",
                            "producer_granule_id": "SMAP_L3_SM_P_E_20260705_R19240_001.h5",
                            "time_start": "2026-07-05T00:00:00Z",
                            "time_end": "2026-07-05T23:59:59Z",
                            "links": [
                                {"href": "https://data.nsidc.earthdatacloud.nasa.gov/smap1.h5"}
                            ],
                        },
                        {
                            "id": "S2",
                            "producer_granule_id": "SMAP_L3_SM_P_E_20260706_R19240_001.h5",
                            "time_start": "2026-07-06T00:00:00Z",
                            "time_end": "2026-07-06T23:59:59Z",
                            "links": [
                                {"href": "https://data.nsidc.earthdatacloud.nasa.gov/smap2.h5"}
                            ],
                        },
                    ]
                }
            }
            return Response(200, content=json.dumps(cmr).encode("utf-8"))
        if request.url.path.endswith("smap2.h5"):
            return Response(200, content=s2)
        return Response(200, content=s1)

    handler = SMAPHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path / "raw_smap",
        transport=MockTransport(handle_http),
    )
    ds = await handler.handle_payload(
        {
            "overpass": "AM",
            "domain": "global",
            "start_time": datetime(2026, 7, 5, tzinfo=UTC),
            "end_time": datetime(2026, 7, 7, tzinfo=UTC),
        }
    )
    sm_ts = ds.extensions["time_series"]["soil_moisture"]
    assert sm_ts["values"] == [pytest.approx(0.24, abs=1e-4), pytest.approx(0.30, abs=1e-4)]
    assert sm_ts["overpass_tags"] == ["AM", "AM"]
    assert sm_ts["qa_layers"]["retrieval_qual_flag"] == [0, 8]
    assert ds.extensions["overpass_mode"] == "am_only"
