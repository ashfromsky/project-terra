"""API tests for POST /api/v1/assessments/compare."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app
from terra.modules.auth.api.dependencies import get_github_oauth_client
from terra.modules.auth.domain.entities import GitHubProfile

_BOX = {
    "type": "Polygon",
    "coordinates": [[[24.0, 48.0], [25.0, 48.0], [25.0, 49.0], [24.0, 49.0], [24.0, 48.0]]],
}


class _StubGitHubClient:
    def __init__(self, github_id: int, login: str) -> None:
        self.profile = GitHubProfile(github_id=github_id, github_login=login)

    def build_authorize_url(self, state: str) -> str:
        return f"https://github.com/login/oauth/authorize?client_id=gh&state={state}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        return self.profile


def _login_headers(
    client: TestClient,
    github_stub: _StubGitHubClient,
    github_id: int,
    login: str,
) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse

    github_stub.profile = GitHubProfile(github_id=github_id, github_login=login)
    auth_url = client.get("/api/v1/auth/github/login").json()["authorizeUrl"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    cb = client.get("/api/v1/auth/github/callback", params={"code": "ok", "state": state})
    token = cb.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def _build_inline_ndvi_dataset(dataset_id: str, slope: float) -> dict[str, Any]:
    from terra_scientific.domain.enums import (
        DataSourceId,
        TemporalCadence,
        TemporalSemantics,
        VariableSemanticKind,
    )
    from terra_scientific.domain.models.dataset import (
        ObservationSeries,
        ScientificDataset,
        SpatialSupport,
        TemporalMetadata,
        VariableMetadata,
    )

    timestamps: list[datetime] = []
    values: list[float] = []
    t = datetime(2018, 1, 1, tzinfo=UTC)
    for i in range(60):
        year = 2018 + (i // 12)
        month = (i % 12) + 1
        timestamps.append(datetime(year, month, 1, tzinfo=UTC))
        base = 0.45 + slope * i
        if i == 50:
            base -= 0.14
        values.append(round(base, 4))

    meta = VariableMetadata(
        name="NDVI",
        canonical_name="NDVI",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        is_scaled=True,
        fill_values=(-3000.0,),
        valid_range=(-0.2, 1.0),
    )
    ds = ScientificDataset(
        dataset_id=dataset_id,
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        provider="modis",
        spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=250.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.MONTHLY,
            semantics=TemporalSemantics.COMPOSITE,
            composite_days=16,
            start=t,
            end=datetime(2022, 12, 31, tzinfo=UTC) + timedelta(days=1),
        ),
        variables={"NDVI": meta},
        series={
            "NDVI": ObservationSeries(
                timestamps=timestamps,
                values=values,
                qa_layers={"pixel_reliability": [0] * len(values)},
                metadata=meta,
            )
        },
    )
    return ds.model_dump(mode="json")


def _assessment_payload(
    title: str,
    region_id: str,
    dataset_id: str,
    slope: float,
    *,
    execute_now: bool = True,
) -> dict[str, Any]:
    return {
        "title": title,
        "regionId": region_id,
        "executeNow": execute_now,
        "requestConfig": {
            "request_id": f"req-{dataset_id}",
            "analysis_start": "2020-01-01T00:00:00Z",
            "analysis_end": "2022-12-31T00:00:00Z",
            "target_cadence": "monthly",
            "baseline": {
                "baseline_type": "fixed_reference",
                "start": "2018-01-01T00:00:00Z",
                "end": "2019-12-31T00:00:00Z",
                "min_years_required": 2,
                "min_samples_per_bin": 2,
            },
        },
        "inlineDatasets": [_build_inline_ndvi_dataset(dataset_id, slope)],
    }


def test_compare_assessments_computes_deltas_and_enforces_rules() -> None:
    github_stub = _StubGitHubClient(101, "researcher-1")
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            github_client_id="cid",
            github_client_secret="csec",
        )
    )
    app.dependency_overrides[get_github_oauth_client] = lambda: github_stub

    with TestClient(app) as client:
        h1 = _login_headers(client, github_stub, 101, "researcher-1")
        h2 = _login_headers(client, github_stub, 202, "researcher-2")

        region_a = client.post(
            "/api/v1/regions",
            headers=h1,
            json={"name": "Site Alpha", "role": "regionA", "geometry": _BOX},
        ).json()["id"]
        region_b = client.post(
            "/api/v1/regions",
            headers=h1,
            json={"name": "Site Beta", "role": "regionB", "geometry": _BOX},
        ).json()["id"]

        a1 = client.post(
            "/api/v1/assessments",
            headers=h1,
            json=_assessment_payload("Alpha Recovery", region_a, "ds-alpha", 0.004),
        )
        assert a1.status_code == 201
        id1 = a1.json()["id"]

        a2 = client.post(
            "/api/v1/assessments",
            headers=h1,
            json=_assessment_payload("Beta Decline", region_b, "ds-beta", -0.002),
        )
        assert a2.status_code == 201
        id2 = a2.json()["id"]

        compared = client.post(
            "/api/v1/assessments/compare",
            headers=h1,
            json={"primaryAssessmentId": id1, "comparisonAssessmentId": id2},
        )
        assert compared.status_code == 200
        body = compared.json()
        assert body["sharedVariables"] == ["NDVI"]
        assert body["primary"]["id"] == id1
        assert body["comparison"]["id"] == id2
        ndvi_cmp = body["variableComparisons"][0]
        assert ndvi_cmp["variableName"] == "NDVI"
        assert ndvi_cmp["sensSlopeDelta"] > 0.0
        assert ndvi_cmp["meanValueDelta"] > 0.0
        assert any("distinct Areas of Interest" in w for w in body["compatibilityWarnings"])
        assert any("unavailable_unvalidated" in n for n in body["methodologyNotes"])

        self_cmp = client.post(
            "/api/v1/assessments/compare",
            headers=h1,
            json={"primaryAssessmentId": id1, "comparisonAssessmentId": id1},
        )
        assert self_cmp.status_code == 422

        queued = client.post(
            "/api/v1/assessments",
            headers=h1,
            json=_assessment_payload("Queued Run", region_a, "ds-queued", 0.001, execute_now=False),
        )
        assert queued.status_code == 201
        queued_cmp = client.post(
            "/api/v1/assessments/compare",
            headers=h1,
            json={"primaryAssessmentId": id1, "comparisonAssessmentId": queued.json()["id"]},
        )
        assert queued_cmp.status_code == 422

        cross_user = client.post(
            "/api/v1/assessments/compare",
            headers=h2,
            json={"primaryAssessmentId": id1, "comparisonAssessmentId": id2},
        )
        assert cross_user.status_code == 403
        assert UUID(id1)
