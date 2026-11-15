"""HTTP service port for Core to coordinate with Geospatial Harmonization Service."""

from typing import Any, Protocol


class GhsServiceClient(Protocol):
    """Port abstracting GHS discovery, ingestion jobs, and dataset inspection APIs."""

    async def list_providers(self) -> list[dict[str, Any]]:
        """List registered GHS environmental data providers and product capabilities."""
        ...

    async def discover_observations(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Discover candidate satellite or station observations in GHS."""
        ...

    async def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit an asynchronous harmonization job to GHS."""
        ...

    async def run_harmonize_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a bounded harmonization run synchronously on GHS."""
        ...

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Retrieve current status for a submitted GHS job."""
        ...

    async def list_datasets(
        self,
        *,
        provider: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List prepared datasets persisted by GHS."""
        ...

    async def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Fetch full prepared dataset metadata and embedded series from GHS."""
        ...

    async def get_dataset_asset_url(
        self,
        dataset_id: str,
        *,
        asset_id: str | None = None,
        expires_in: int | None = None,
    ) -> dict[str, Any]:
        """Request a download descriptor and optional presigned R2 URL from GHS."""
        ...

    async def download_dataset_asset_content(
        self,
        dataset_id: str,
        *,
        asset_id: str | None = None,
    ) -> tuple[bytes, str, str]:
        """Download binary asset bytes, media_type, and filename from GHS."""
        ...
