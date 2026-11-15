"""Tests for adaptive multi-year CMR discovery, temporal QA retention, and unit parity."""

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.application import HarmonizationService
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.models.dataset import (
    ProvenanceRecord,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    TemporalSpec,
    VariableSpec,
)
from geospatial_harmonization.domain.models.harmonization import HarmonizationPlan
from geospatial_harmonization.handlers import build_default_handler_registry
from geospatial_harmonization.handlers.base import (
    CmrGranule,
    build_time_series_extension,
    discover_cmr_granules,
    select_representative_granules,
)
from geospatial_harmonization.handlers.gpm_imerg import GPMIMERGPayload
from geospatial_harmonization.handlers.modis import MODISPayload
from geospatial_harmonization.handlers.nasa_power import NASAPowerHandler
from geospatial_harmonization.handlers.smap import SMAPPayload
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.repositories import SqlAlchemyDatasetRepository
from geospatial_harmonization.infrastructure.storage import LocalObjectStore


async def test_discover_cmr_granules_paginates_and_sorts_chronologically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    requests_seen: list[tuple[str, str | None]] = []

    def handle_cmr(request: Request) -> Response:
        page_num = request.url.params.get("page_num", "1")
        sort_key = request.url.params.get("sort_key[]")
        requests_seen.append((page_num, sort_key))
        if page_num == "1":
            entries = [
                {
                    "id": "G1",
                    "producer_granule_id": "MOD13Q1.A2021001.h18v09.061.hdf",
                    "time_start": "2021-01-01T00:00:00Z",
                    "time_end": "2021-01-17T00:00:00Z",
                    "links": [{"href": "https://e4ftl01.cr.usgs.gov/MOD13Q1_2021_01.hdf"}],
                },
                {
                    "id": "G2",
                    "producer_granule_id": "MOD13Q1.A2022001.h18v09.061.hdf",
                    "time_start": "2022-01-01T00:00:00Z",
                    "time_end": "2022-01-17T00:00:00Z",
                    "links": [{"href": "https://e4ftl01.cr.usgs.gov/MOD13Q1_2022_01.hdf"}],
                },
            ]
        elif page_num == "2":
            entries = [
                {
                    "id": "G3",
                    "producer_granule_id": "MOD13Q1.A2024001.h18v09.061.hdf",
                    "time_start": "2024-01-01T00:00:00Z",
                    "time_end": "2024-01-17T00:00:00Z",
                    "links": [{"href": "https://e4ftl01.cr.usgs.gov/MOD13Q1_2024_01.hdf"}],
                }
            ]
        else:
            entries = []
        return Response(200, content=json.dumps({"feed": {"entry": entries}}).encode("utf-8"))

    granules = await discover_cmr_granules(
        "https://cmr.earthdata.nasa.gov/search",
        "MOD13Q1.061",
        datetime(2021, 1, 1, tzinfo=UTC),
        datetime(2024, 12, 31, tzinfo=UTC),
        (".hdf",),
        page_size=2,
        max_pages=4,
        transport=MockTransport(handle_cmr),
    )
    assert [g.granule_id for g in granules] == [
        "MOD13Q1.A2021001.h18v09.061.hdf",
        "MOD13Q1.A2022001.h18v09.061.hdf",
        "MOD13Q1.A2024001.h18v09.061.hdf",
    ]
    assert requests_seen == [("1", "+start_date"), ("2", "+start_date")]


def test_select_representative_granules_stratifies_multiyear_span() -> None:
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    granules: list[CmrGranule] = []
    for idx in range(48):
        dt = t0 + timedelta(days=idx * 30)
        granules.append(
            CmrGranule(
                granule_id=f"MOD13Q1_{idx:02d}.hdf",
                producer_granule_id=f"MOD13Q1_{idx:02d}.hdf",
                short_name="MOD13Q1",
                version="061",
                title=f"MOD13Q1 {idx}",
                data_url=f"https://e4ftl01.cr.usgs.gov/MOD13Q1_{idx:02d}.hdf",
                time_start=dt,
                time_end=dt + timedelta(days=16),
            )
        )
    selected, meta = select_representative_granules(granules, 12, window_start=t0)
    assert len(selected) == 12
    assert meta["selection_strategy"] == "uniform_temporal_stratification"
    years = {g.time_start.year for g in selected if g.time_start is not None}
    assert years == {2021, 2022, 2023, 2024}
    assert selected[0].time_start == granules[0].time_start
    assert selected[-1].time_start == granules[-1].time_start


def test_handler_payload_max_granules_supports_multiyear_cap() -> None:
    m = MODISPayload(
        product="MOD13Q1.061",
        start_time=datetime(2021, 1, 1, tzinfo=UTC),
        max_granules=120,
    )
    g = GPMIMERGPayload(start_time=datetime(2021, 1, 1, tzinfo=UTC), max_granules=120)
    s = SMAPPayload(start_time=datetime(2021, 1, 1, tzinfo=UTC), max_granules=120)
    assert m.max_granules == 120
    assert g.max_granules == 120
    assert s.max_granules == 120


async def test_temporal_harmonization_preserves_qa_counts_overpass_and_converts_sum_units(
    tmp_path: Path,
) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'th.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        svc = HarmonizationService(
            handlers=build_default_handler_registry(
                settings=Settings(_env_file=None, environment="test")
            ),
            storage=LocalObjectStore(tmp_path / "store"),
            datasets=SqlAlchemyDatasetRepository(build_session_factory(engine)),
        )
        ds = SpatialDataset(
            dataset_id=uuid4(),
            source_id="test_src",
            provider="smap",
            product="SPL3SMP_E.006",
            product_version="006",
            variables={
                "soil_moisture": VariableSpec(
                    "soil_moisture", "cm^3/cm^3", "float32", ("time",), "continuous_intensive"
                ),
                "PRECTOTCORR": VariableSpec(
                    "PRECTOTCORR", "mm/day", "float32", ("time",), "continuous_extensive"
                ),
            },
            units={"soil_moisture": "cm^3/cm^3", "PRECTOTCORR": "mm/day"},
            spatial_metadata=SpatialMetadata("point", "EPSG:4326"),
            temporal_metadata=TemporalSpec(
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 3, tzinfo=UTC),
                "daily",
                "interval",
            ),
            quality_metadata=QualityMetadata("test"),
            assets=(),
            provenance=ProvenanceRecord(
                "smap",
                "SPL3SMP_E.006",
                "006",
                datetime.now(UTC),
                "0.1.0",
                source_urls=("https://example.org",),
            ),
            extensions={
                "time_series": {
                    "soil_moisture": build_time_series_extension(
                        timestamps=[
                            datetime(2024, 1, 1, tzinfo=UTC),
                            datetime(2024, 1, 2, tzinfo=UTC),
                        ],
                        values=[0.20, 0.30],
                        units="cm^3/cm^3",
                        qa_layers={"retrieval_qual_flag": [0, 0]},
                        overpass_tags=["AM", "AM"],
                        valid_pixel_counts=[10, 20],
                        total_pixel_counts=[10, 20],
                    ),
                    "PRECTOTCORR": build_time_series_extension(
                        timestamps=[
                            datetime(2024, 1, 1, tzinfo=UTC),
                            datetime(2024, 1, 2, tzinfo=UTC),
                        ],
                        values=[10.0, 5.0],
                        units="mm/day",
                        qa_layers={"precipitationQualityIndex": [9.0, 7.0]},
                        valid_pixel_counts=[1, 1],
                        total_pixel_counts=[1, 1],
                    ),
                }
            },
        )
        plan = HarmonizationPlan(
            plan_id=uuid4(),
            provider="smap",
            product="SPL3SMP_E.006",
            request_payload={"start_time": "2024-01-01T00:00:00Z"},
            target_temporal=TemporalSpec(
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 2, 1, tzinfo=UTC),
                "monthly",
                "interval",
                aggregation="sum",
            ),
        )
        out_ds, _warnings = svc._apply_temporal_harmonization(ds, plan)
        sm_ts = out_ds.extensions["time_series"]["soil_moisture"]
        pr_ts = out_ds.extensions["time_series"]["PRECTOTCORR"]

        assert sm_ts["values"] == [pytest.approx(0.25)]
        assert sm_ts["qa_layers"] == {"retrieval_qual_flag": [0]}
        assert sm_ts["overpass_tags"] == ["AM"]
        assert sm_ts["valid_pixel_counts"] == [30]
        assert sm_ts["total_pixel_counts"] == [30]

        assert pr_ts["values"] == [pytest.approx(15.0)]
        assert pr_ts["units"] == "mm"
        assert pr_ts["qa_layers"]["precipitationQualityIndex"] == [pytest.approx(8.0)]
        assert out_ds.units["PRECTOTCORR"] == "mm"
    finally:
        await engine.dispose()


async def test_nasa_power_solar_radiation_semantics_match_scientific_core(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("129.164.179.22", 443))],
    )

    def handle_http(_request: Request) -> Response:
        doc = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [30.5, 50.4, 150.0]},
            "parameters": {"ALLSKY_SFC_SW_DWN": {"units": "MJ/m^2/day"}},
            "properties": {"parameter": {"ALLSKY_SFC_SW_DWN": {"20240701": 18.5}}},
        }
        return Response(200, content=json.dumps(doc).encode("utf-8"))

    handler = NASAPowerHandler(
        settings=Settings(_env_file=None, environment="test"),
        raw_dir=tmp_path,
        transport=MockTransport(handle_http),
    )
    ds = await handler.handle_payload(
        {
            "product": "power_daily",
            "mode": "point",
            "temporal": "daily",
            "parameters": ("ALLSKY_SFC_SW_DWN",),
            "start_date": "2024-07-01",
            "end_date": "2024-07-01",
            "latitude": 50.4,
            "longitude": 30.5,
        }
    )
    assert ds.variables["ALLSKY_SFC_SW_DWN"].semantics == "continuous_extensive"
