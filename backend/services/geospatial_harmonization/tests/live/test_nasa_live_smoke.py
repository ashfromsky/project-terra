"""Optional opt-in live smoke tests against real NASA POWER, CMR, MODIS, GPM, and SMAP endpoints.

Run explicitly with:
    RUN_LIVE_NASA_TESTS=1 uv run pytest -m live -v -s
Never enabled during default offline CI/unit runs.
"""

import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.handlers.gpm_imerg import GPMIMERGHandler
from geospatial_harmonization.handlers.modis import MODISHandler
from geospatial_harmonization.handlers.nasa_power import NASAPowerHandler
from geospatial_harmonization.handlers.smap import SMAPHandler

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_NASA_TESTS") != "1",
        reason="Live NASA smoke tests are opt-in (set RUN_LIVE_NASA_TESTS=1 to run)",
    ),
]


def _live_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        local_storage_dir=tmp_path / "store",
        http_timeout_seconds=120.0,
        http_max_retries=2,
        http_retry_backoff_seconds=1.0,
    )


def _require_earthdata_token(cfg: Settings) -> Settings:
    if not cfg.has_earthdata_token():
        pytest.skip("EARTHDATA_TOKEN is not configured")
    return cfg


async def test_live_nasa_power_daily_and_hourly_point(tmp_path: Path) -> None:
    cfg = _live_settings(tmp_path)
    handler = NASAPowerHandler(settings=cfg, raw_dir=tmp_path / "raw")
    daily = await handler.handle_payload(
        {
            "product": "power_daily",
            "mode": "point",
            "temporal": "daily",
            "latitude": 50.45,
            "longitude": 30.52,
            "start_date": date(2024, 7, 1),
            "end_date": date(2024, 7, 3),
            "parameters": ["PRECTOTCORR", "T2M"],
        }
    )
    assert daily.provider == "nasa_power"
    assert daily.units["PRECTOTCORR"] in {"mm/day", "mm/d"}
    assert daily.units["T2M"] in {"C", "degC"}
    assert daily.quality_metadata.valid_observation_fraction is not None
    assert daily.quality_metadata.valid_observation_fraction > 0.0
    assert daily.assets[0].size_bytes is not None and daily.assets[0].size_bytes > 0

    hourly = await handler.handle_payload(
        {
            "product": "power_hourly",
            "mode": "point",
            "temporal": "hourly",
            "latitude": 50.45,
            "longitude": 30.52,
            "start_date": date(2024, 7, 1),
            "end_date": date(2024, 7, 2),
            "parameters": ["PRECTOTCORR", "T2M"],
        }
    )
    assert hourly.temporal_metadata.cadence == "1h"
    assert hourly.units["PRECTOTCORR"] in {"mm/hour", "mm/hr"}
    assert hourly.quality_metadata.valid_observation_fraction is not None


async def test_live_cmr_discovery_for_modis_gpm_and_smap(tmp_path: Path) -> None:
    cfg = _live_settings(tmp_path)
    bbox = (30.0, 50.0, 31.0, 51.0)

    modis = await MODISHandler(settings=cfg).discover(
        product="MOD13Q1.061",
        bbox=bbox,
        start_time=datetime(2024, 7, 1, tzinfo=UTC),
        end_time=datetime(2024, 7, 20, tzinfo=UTC),
        limit=3,
    )
    assert len(modis) >= 1 and modis[0].product == "MOD13Q1.061"

    gpm = await GPMIMERGHandler(settings=cfg).discover(
        product="GPM_3IMERGHH.07",
        bbox=bbox,
        start_time=datetime(2024, 7, 1, 0, 0, tzinfo=UTC),
        end_time=datetime(2024, 7, 1, 1, 0, tzinfo=UTC),
        limit=3,
    )
    assert len(gpm) >= 1 and gpm[0].product == "GPM_3IMERGHH.07"

    smap = await SMAPHandler(settings=cfg).discover(
        product="SPL3SMP_E.006",
        bbox=bbox,
        start_time=datetime(2024, 7, 1, tzinfo=UTC),
        end_time=datetime(2024, 7, 2, tzinfo=UTC),
        limit=3,
    )
    assert len(smap) >= 1 and smap[0].product == "SPL3SMP_E.006"


async def test_live_modis_granule_download_and_hdf4_decode(tmp_path: Path) -> None:
    cfg = _require_earthdata_token(_live_settings(tmp_path))
    handler = MODISHandler(settings=cfg, raw_dir=tmp_path / "raw")
    ds = await handler.handle_payload(
        {
            "product": "MOD13Q1.061",
            "start_time": datetime(2024, 7, 1, tzinfo=UTC),
            "bbox": (30.0, 50.0, 31.0, 51.0),
        }
    )
    assert ds.provider == "modis"
    assert ds.granule_id is not None and "MOD13Q1" in ds.granule_id
    assert ds.quality_metadata.valid_observation_fraction is not None
    assert "NDVI" in ds.variables and "EVI" in ds.variables
    assert ds.assets[0].checksum_sha256 is not None


async def test_live_gpm_imerg_granule_download_and_hdf5_decode(tmp_path: Path) -> None:
    cfg = _require_earthdata_token(_live_settings(tmp_path))
    handler = GPMIMERGHandler(settings=cfg, raw_dir=tmp_path / "raw")
    ds = await handler.handle_payload(
        {
            "product": "GPM_3IMERGHH.07",
            "start_time": datetime(2024, 7, 1, 0, 0, tzinfo=UTC),
            "bbox": (30.0, 50.0, 31.0, 51.0),
        }
    )
    assert ds.provider == "gpm_imerg"
    assert ds.granule_id is not None
    assert ds.units.get("precipitation") == "mm/hour"
    assert ds.assets[0].checksum_sha256 is not None


async def test_live_smap_granule_download_and_hdf5_decode(tmp_path: Path) -> None:
    cfg = _require_earthdata_token(_live_settings(tmp_path))
    handler = SMAPHandler(settings=cfg, raw_dir=tmp_path / "raw")
    ds = await handler.handle_payload(
        {
            "product": "SPL3SMP_E.006",
            "start_time": datetime(2024, 7, 1, tzinfo=UTC),
            "bbox": (30.0, 50.0, 31.0, 51.0),
            "overpass": "AM",
        }
    )
    assert ds.provider == "smap"
    assert ds.granule_id is not None
    assert "soil_moisture" in ds.variables
    assert ds.quality_metadata.valid_observation_fraction is not None
