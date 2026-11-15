from pathlib import Path

from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app


def _settings(dist_dir: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        cors_origins=[],
        frontend_dist_dir=str(dist_dir),
    )


def test_core_serves_spa_and_assets_from_frontend_dist(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>TERRA SPA</body></html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('terra')", encoding="utf-8")

    app = create_app(_settings(dist))
    with TestClient(app) as client:
        assert client.get("/").text == "<html><body>TERRA SPA</body></html>"
        assert client.get("/explore").text == "<html><body>TERRA SPA</body></html>"
        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert asset.text == "console.log('terra')"


def test_spa_fallback_does_not_mask_unknown_api_routes(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("TERRA SPA", encoding="utf-8")

    app = create_app(_settings(dist))
    with TestClient(app) as client:
        response = client.get("/api/v1/not-a-real-route")
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
