"""Tests for API request/response schema validation and domain mapping."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geospatial_harmonization.api.schemas import HarmonizeRequest, JobOut
from geospatial_harmonization.domain.exceptions import InvalidGridSpecError
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob


def test_harmonize_request_maps_to_domain_plan_and_validates_grid() -> None:
    req = HarmonizeRequest.model_validate(
        {
            "provider": "generic",
            "product": "ndvi",
            "request_payload": {"url": "https://data.example.org/ndvi.tif"},
            "target_grid": {
                "crs": "EPSG:4326",
                "resolution_x": 0.5,
                "resolution_y": 0.5,
                "resolution_unit": "degree",
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 2.0, "max_y": 2.0},
            },
            "target_temporal": {
                "start": "2026-07-01T00:00:00Z",
                "end": "2026-07-02T00:00:00Z",
                "cadence": "daily",
                "semantics": "interval",
            },
            "variables": ["band_1"],
        }
    )
    plan = req.to_plan()
    assert plan.target_grid is not None
    assert plan.target_grid.resolved().width == 4
    assert plan.variables == ("band_1",)

    now = datetime(2026, 7, 1, tzinfo=UTC)
    job = HarmonizationJob(uuid4(), plan, "pending", now, now)
    out = JobOut.from_domain(job)
    assert out.provider == "generic" and out.status == "pending"

    bad = HarmonizeRequest.model_validate(
        {
            "provider": "generic",
            "product": "ndvi",
            "target_grid": {
                "crs": "EPSG:4326",
                "resolution_x": 0.3,
                "resolution_y": 0.3,
                "resolution_unit": "degree",
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
            },
        }
    )
    with pytest.raises(InvalidGridSpecError):
        bad.to_plan()
