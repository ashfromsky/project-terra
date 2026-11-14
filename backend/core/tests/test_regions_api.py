"""API tests for all 8 Regions endpoints, auth enforcement, and ownership."""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app
from terra.modules.auth.api.dependencies import get_github_oauth_client
from terra.modules.auth.domain.entities import GitHubProfile

_BOX_1 = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
_BOX_2 = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


class _StubGitHub:
    def __init__(self, profile: GitHubProfile) -> None:
        self.profile = profile

    def build_authorize_url(self, state: str) -> str:
        return f"https://github.com/login/oauth/authorize?state={state}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        return self.profile


def _login_headers(client: TestClient, stub: _StubGitHub, gh_id: int, login: str) -> dict[str, str]:
    stub.profile = GitHubProfile(github_id=gh_id, github_login=login)
    url = client.get("/api/v1/auth/github/login").json()["authorizeUrl"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get("/api/v1/auth/github/callback", params={"code": "c", "state": state})
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


def test_regions_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/regions").status_code == 401


def test_regions_crud_geometry_statistics_and_isolation() -> None:
    stub = _StubGitHub(GitHubProfile(github_id=1, github_login="user1"))
    app = create_app(Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:"))
    app.dependency_overrides[get_github_oauth_client] = lambda: stub

    with TestClient(app) as client:
        h1 = _login_headers(client, stub, 1001, "owner1")
        h2 = _login_headers(client, stub, 1002, "owner2")

        created = client.post(
            "/api/v1/regions",
            headers=h1,
            json={"name": "Congo", "role": "regionA", "shapeType": "polygon", "geometry": _BOX_1},
        )
        assert created.status_code == 201
        rid, area_1 = created.json()["id"], created.json()["approxAreaKm2"]

        assert len(client.get("/api/v1/regions", headers=h1).json()) == 1
        assert client.get(f"/api/v1/regions/{rid}", headers=h1).json()["name"] == "Congo"
        assert client.get(f"/api/v1/regions/{rid}", headers=h2).status_code == 403

        patched = client.patch(
            f"/api/v1/regions/{rid}", headers=h1, json={"name": "Congo Core", "description": "AOI"}
        )
        assert patched.status_code == 200 and patched.json()["description"] == "AOI"

        feat = client.get(f"/api/v1/regions/{rid}/geometry", headers=h1)
        assert feat.status_code == 200 and feat.json()["type"] == "Feature"
        assert feat.json()["properties"]["sourceCrs"] == "EPSG:4326"

        regeom = client.put(
            f"/api/v1/regions/{rid}/geometry",
            headers=h1,
            json={"geometry": _BOX_2, "shapeType": "rectangle"},
        )
        assert regeom.status_code == 200 and regeom.json()["approxAreaKm2"] > area_1 * 3

        stats = client.get(f"/api/v1/regions/{rid}/statistics", headers=h1)
        assert stats.status_code == 200 and stats.json()["observationStatus"] == "unavailable"

        bad = client.post(
            "/api/v1/regions", headers=h1, json={"name": "Bad", "geometry": {"type": "Point"}}
        )
        assert bad.status_code == 422

        assert client.delete(f"/api/v1/regions/{rid}", headers=h1).status_code == 204
        assert client.get(f"/api/v1/regions/{rid}", headers=h1).status_code == 404
