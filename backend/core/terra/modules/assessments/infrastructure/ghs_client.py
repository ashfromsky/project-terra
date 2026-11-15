"""HTTP client fetching prepared datasets from the Geospatial Harmonization Service."""

import re

import httpx
from terra_scientific.adapters.ghs import map_ghs_dataset_payload
from terra_scientific.domain.exceptions import ScientificCoreError
from terra_scientific.domain.models.dataset import ScientificDataset

from terra.config import Settings
from terra.modules.assessments.domain.exceptions import GhsIntegrationError

_VALID_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class HttpxGhsDatasetClient:
    """Async httpx adapter implementing GhsDatasetClient against GHS HTTP API."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.ghs_base_url.rstrip("/")
        self._timeout = settings.ghs_timeout_seconds
        self._transport = transport

    async def fetch_dataset(self, dataset_id: str) -> ScientificDataset:
        """Fetch GET /api/v1/datasets/{dataset_id} and map to ScientificDataset."""
        cleaned = dataset_id.strip()
        if not _VALID_DATASET_ID_RE.fullmatch(cleaned):
            raise GhsIntegrationError(f"Invalid GHS dataset identifier: '{dataset_id}'")

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.get(f"/api/v1/datasets/{cleaned}")
        except httpx.HTTPError as exc:
            raise GhsIntegrationError(
                f"Failed to contact GHS service for dataset '{cleaned}': {exc}"
            ) from exc

        if response.status_code >= 400:
            raise GhsIntegrationError(
                f"GHS service returned HTTP {response.status_code} for dataset '{cleaned}'"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise GhsIntegrationError(
                f"GHS dataset '{cleaned}' returned non-JSON response"
            ) from exc

        if not isinstance(payload, dict):
            raise GhsIntegrationError(f"GHS dataset '{cleaned}' payload must be a JSON object")

        try:
            return map_ghs_dataset_payload(payload)
        except (ScientificCoreError, TypeError, ValueError, KeyError) as exc:
            raise GhsIntegrationError(
                f"GHS dataset '{cleaned}' failed Scientific Core mapping: {exc}"
            ) from exc
