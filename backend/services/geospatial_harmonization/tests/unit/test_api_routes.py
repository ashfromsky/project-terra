"""Tests for FastAPI liveness, readiness, and degraded dependency responses."""

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from geospatial_harmonization.api.dependencies import get_db_engine
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.infrastructure.database import build_async_engine
from geospatial_harmonization.main import create_app


async def test_health_and_readiness_probes(tmp_path: Path) -> None:
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}",
        local_storage_dir=tmp_path / "store",
    )
    app = create_app(cfg)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        for path in ("/health", "/api/v1/health"):
            res = await client.get(path)
            assert res.status_code == 200
            assert res.json()["status"] == "ok"

        for path in ("/ready", "/api/v1/ready"):
            res = await client.get(path)
            assert res.status_code == 200
            body = res.json()
            assert body["status"] == "ready"
            assert body["checks"]["database"]["status"] == "ok"

        bad_engine = build_async_engine("sqlite+aiosqlite:////nonexistent-ghs-dir/bad.db")
        app.dependency_overrides[get_db_engine] = lambda: bad_engine
        try:
            degraded = await client.get("/ready")
            assert degraded.status_code == 503
            assert degraded.json()["status"] == "not_ready"
            assert degraded.json()["checks"]["database"]["status"] == "unavailable"
        finally:
            app.dependency_overrides.clear()
            await bad_engine.dispose()
